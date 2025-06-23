const { Client, GatewayIntentBits, EmbedBuilder, REST, Routes, ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType, StringSelectMenuBuilder, StringSelectMenuOptionBuilder, MessageFlags, ModalBuilder, TextInputBuilder, TextInputStyle } = require('discord.js');
const dotenv = require('dotenv');
const moment = require('moment'); // For date/time handling
const fs = require('fs');     // For file system operations (logging)
const path = require('path'); // For path manipulation (logging)
const crypto = require('crypto'); // For generating random UUIDs

// Import PostgreSQL client
const { Pool } = require('pg');

dotenv.config(); // Load environment variables from .env file

// --- Logging Configuration (Moved to top for early availability) ---
const logDirectory = path.join(__dirname, 'logs');

const ensureLogDirectory = () => {
    if (!fs.existsSync(logDirectory)) {
        fs.mkdirSync(logDirectory, { recursive: true });
    }
};

const getLogFileName = () => {
    return path.join(logDirectory, `bot_log_${moment().format('YYYY-MM-DD')}.log`);
};

const writeToLog = (message) => {
    ensureLogDirectory();
    const logFileName = getLogFileName();
    const timestamp = moment().format('YYYY-MM-DD HH:mm:ss');
    try {
        fs.appendFileSync(logFileName, `[${timestamp}] ${message}\n`);
    } catch (error) {
        console.error(`Failed to write to log file ${logFileName}:`, error);
    }
};

const cleanupOldLogs = () => {
    ensureLogDirectory();
    fs.readdir(logDirectory, (err, files) => {
        if (err) {
            console.error('Error reading log directory for cleanup:', err);
            writeToLog(`Error reading log directory for cleanup: ${err.message}`);
            return;
        }

        files.forEach(file => {
            const filePath = path.join(logDirectory, file);
            const fileNameParts = file.split('_');
            if (fileNameParts.length === 3 && fileNameParts[0] === 'bot' && fileNameParts[1] === 'log' && file.endsWith('.log')) {
                const datePart = fileNameParts[2].split('.')[0];
                const logDate = moment(datePart, 'YYYY-MM-DD');

                if (moment().diff(logDate, 'days') > 5) {
                    fs.unlink(filePath, unlinkErr => {
                        if (unlinkErr) {
                            console.error(`Error deleting old log file ${file}:`, unlinkErr);
                            writeToLog(`Error deleting old log file ${file}: ${unlinkErr.message}`);
                        } else {
                            console.log(`Deleted old log file: ${file}`);
                            writeToLog(`Deleted old log file: ${file}`);
                        }
                    });
                }
            }
        });
    });
};

// --- CONFIGURATION ---
// IMPORTANT: This is the actual ID of your "@SL certified" Discord role.
// This ID is used to conditionally display the "Officer" class.
const SL_CERTIFIED_ROLE_ID = process.env.SL_CERTIFIED_ROLE_ID; // Fetch from .env
// IMPORTANT: This is the actual ID of your "@TC certified" Discord role.
// This ID is used to conditionally display the "Tank Commander" class.
const TC_CERTIFIED_ROLE_ID = process.env.TC_CERTIFIED_ROLE_ID; // Fetch from .env
// IMPORTANT: This is the actual ID of your "Cmdr certified" Discord role.
// This ID is used to conditionally display the "Commander" primary role.
const CMDR_CERTIFIED_ROLE_ID = process.env.CMDR_CERTIFIED_ROLE_ID; // Fetch from .env
// IMPORTANT: This is the actual ID of your "Recon certified" Discord role.
// This ID is used to conditionally display the "Recon" primary role.
const RECON_CERTIFIED_ROLE_ID = process.env.RECON_CERTIFIED_ROLE_ID; // Fetch from .env
// IMPORTANT: Role ID that can delete ANY event. Optional.
const DELETE_EVENT_ROLE_ID = process.env.DELETE_EVENT_ROLE_ID; // Fetch from .env

// NEW: The specific channel ID where discussion threads should be created
const DISCUSSION_CHANNEL_ID = '1386209315685269614';


// Initialize Discord client with necessary intents
const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildMembers, // Required for fetching member data (roles for restriction, e.g., @SL certified)
        GatewayIntentBits.DirectMessages // Required for sending DMs
    ]
});


// --- PostgreSQL Pool (will be populated on client.once('ready')) ---
let pgPool;

// In-memory cache for events (kept in sync with PostgreSQL)
// This cache will be populated on startup and updated manually after DB operations.
let events = {};

// --- Helper Functions ---

const extractRoleIds = (roleString) => {
    if (!roleString) return [];
    // Matches role mentions like <@&123456789012345678> and extracts the ID
    const roleMentions = roleString.match(/<@&(\d+)>/g);
    if (!roleMentions) return [];
    return roleMentions.map(mention => mention.replace(/<@&|>/g, ''));
};

/**
 * Creates and updates the roster embed for a given event, for display within the event thread.
 * @param {string} eventId - The ID of the event.
 * @param {object} guild - The Discord Guild object.
 */
const updateThreadRosterMessage = async (eventId, guild) => {
    const event = events[eventId]; // Get event from in-memory cache
    if (!event || !event.threadId || !event.threadRosterMessageId) {
        writeToLog(`Could not update thread roster for event ${eventId}: Event data or thread/roster message ID missing.`);
        return;
    }

    try {
        const thread = guild.channels.cache.get(event.threadId);
        if (!thread || !thread.isThread()) {
            writeToLog(`Could not update thread roster for event ${eventId}: Thread ${event.threadId} not found or not a thread.`);
            return;
        }

        const rosterMessage = await thread.messages.fetch(event.threadRosterMessageId);

        const rosterEmbed = new EmbedBuilder()
            .setTitle(`__Event Roster for ${event.title}__`)
            .setDescription('**Accepted Participants Breakdown:**')
            .setColor(0x0099ff);

        const acceptedAttendees = event.attendees.filter(a => a.rsvpStatus === 'Attending');
        const rolesForDisplay = ['Commander', 'Infantry', 'Armour', 'Recon'];
        writeToLog(`[updateThreadRosterMessage] Event ${eventId} - Accepted Attendees for roster display: ${JSON.stringify(acceptedAttendees.map(a => `${a.userId}:${a.primaryRole}:${a.className}:${a.emoji}`))}`);


        for (let i = 0; i < rolesForDisplay.length; i++) {
            const roleName = rolesForDisplay[i];
            const membersInRole = acceptedAttendees
                .filter(a => a.primaryRole === roleName)
                .map(attendee => { // Directly use 'attendee' as the iterated object
                    // --- Added logging for emoji check during embed build ---
                    writeToLog(`[updateThreadRosterMessage] Attendee ${attendee.userId} in role ${roleName}: Emoji is "${attendee.emoji}"`);
                    // --- End Added logging ---
                    return attendee.emoji
                        ? `<@${attendee.userId}> ${attendee.emoji}`
                        : `<@${attendee.userId}>`; // Fallback if no emoji set for some reason
                });

            const fieldValue = membersInRole.length > 0 ? membersInRole.join('\n') : 'No one';
            // Find the emoji for the primary role for the field name
            const primaryRoleObj = event.roles.find(r => r.primaryRole === roleName);
            const roleEmoji = primaryRoleObj ? primaryRoleObj.emoji : '';
            // Change here: Make role fields NOT inline for new line
            rosterEmbed.addFields({ name: `${roleName} ${roleEmoji}`, value: fieldValue, inline: false });
        }
        
        const tentativeAttendees = event.attendees
            .filter(a => a.rsvpStatus === 'Tentative')
            .map(a => `<@${a.userId}>`);
        const declinedAttendees = event.attendees
            .filter(a => a.rsvpStatus === 'Declined')
            .map(a => `<@${a.userId}>`);

        writeToLog(`[updateThreadRosterMessage] Event ${eventId} - Tentative Attendees: ${JSON.stringify(tentativeAttendees)}`);
        writeToLog(`[updateThreadRosterMessage] Event ${eventId} - Declined Attendees: ${JSON.stringify(declinedAttendees)}`);


        rosterEmbed.addFields(
            { name: 'Tentative 🤔', value: tentativeAttendees.length > 0 ? tentativeAttendees.join('\n') : 'No one', inline: false },
            { name: 'Declined ❌', value: declinedAttendees.length > 0 ? declinedAttendees.join('\n') : 'No one', inline: false }
        );

        await rosterMessage.edit({ embeds: [rosterEmbed] });
        writeToLog(`Thread roster for event "${event.title}" (ID: ${eventId}) updated.`);

    } catch (error) {
        console.error(`Failed to update thread roster message for event ${eventId}:`, error);
        writeToLog(`Failed to update thread roster message for event ${eventId}: ${error.message}`);
    }
};


/**
 * Updates the main event message embed with the current roster breakdown.
 * @param {string} eventId - The ID of the event.
 * @param {object} guild - The Discord Guild object.
 */
const updateEventRosterEmbed = async (eventId, guild) => {
    const event = events[eventId]; // Get event from in-memory cache
    if (!event || !event.channelId || !event.messageId) {
        writeToLog(`Could not update roster for event ${eventId}: Event data or message/channel ID missing.`);
        return;
    }

    try {
        const channel = guild.channels.cache.get(event.channelId);
        if (!channel) {
            writeToLog(`Could not update roster for event ${eventId}: Channel ${event.channelId} not found.`);
            return;
        }
        const eventMessage = await channel.messages.fetch(event.messageId);

        const updatedEmbed = new EmbedBuilder()
            .setTitle(`Event: ${event.title}`)
            .setDescription(event.description)
            .addFields(
                { name: 'Date', value: moment(event.date, 'DD-MM-YYYY').format('DD-MM-YYYY') },
                { name: 'Time', value: `${event.startTime} - ${event.endTime} (24h format)` }
            );

        if (event.restrictedRoles && event.restrictedRoles.length > 0) {
            const roleMentions = event.restrictedRoles.map(id => `<@&${id}>`).join(', ');
            updatedEmbed.addFields({ name: 'Restricted To Roles', value: roleMentions, inline: false });
        }

        if (event.threadOpenHoursBefore > 0) {
            const openTimeMoment = moment(`${event.date} ${event.startTime}`, 'DD-MM-YYYY HH:mm').subtract(event.threadOpenHoursBefore, 'hours');
            updatedEmbed.addFields({ name: 'Discussion Thread Opens', value: `**${openTimeMoment.format('DD-MM-YYYY HH:mm')}** (${openTimeMoment.fromNow()})`, inline: false });
        } else {
            updatedEmbed.addFields({ name: 'Discussion Thread', value: `Will open at event start time.`, inline: false });
        }

        const acceptedAttendees = event.attendees.filter(a => a.rsvpStatus === 'Attending');
        const rolesForDisplay = ['Commander', 'Infantry', 'Armour', 'Recon'];
        writeToLog(`[updateEventRosterEmbed] Event ${eventId} - Accepted Attendees for embed display: ${JSON.stringify(acceptedAttendees.map(a => `${a.userId}:${a.primaryRole}:${a.className}:${a.emoji}`))}`);


        for (let i = 0; i < rolesForDisplay.length; i++) {
            const roleName = rolesForDisplay[i];
            const membersInRole = acceptedAttendees
                .filter(a => a.primaryRole === roleName)
                .map(attendee => { // Directly use 'attendee' as the iterated object
                    // --- Added logging for emoji check during embed build ---
                    writeToLog(`[updateEventRosterEmbed] Attendee ${attendee.userId} in role ${roleName}: Emoji is "${attendee.emoji}"`);
                    // --- End Added logging ---
                    return attendee.emoji
                        ? `<@${attendee.userId}> ${attendee.emoji}`
                        : `<@${attendee.userId}>`; // Fallback if no emoji set for some reason
                });


            const fieldValue = membersInRole.length > 0 ? membersInRole.join('\n') : 'No one';
            // Find the emoji for the primary role for the field name
            const primaryRoleObj = event.roles.find(r => r.primaryRole === roleName);
            const roleEmoji = primaryRoleObj ? primaryRoleObj.emoji : '';
            // Change here: Make role fields NOT inline for new line
            updatedEmbed.addFields({ name: `${roleName} ${roleEmoji}`, value: fieldValue, inline: false });
        }

        const tentativeAttendees = event.attendees
            .filter(a => a.rsvpStatus === 'Tentative')
            .map(a => `<@${a.userId}>`);
        const declinedAttendees = event.attendees
            .filter(a => a.rsvpStatus === 'Declined')
            .map(a => `<@${a.userId}>`);

        writeToLog(`[updateEventRosterEmbed] Event ${eventId} - Tentative Attendees: ${JSON.stringify(tentativeAttendees)}`);
        writeToLog(`[updateEventRosterEmbed] Event ${eventId} - Declined Attendees: ${JSON.stringify(declinedAttendees)}`);

        updatedEmbed.addFields(
            { name: 'Tentative 🤔', value: tentativeAttendees.length > 0 ? tentativeAttendees.join('\n') : 'No one', inline: false },
            { name: 'Declined ❌', value: declinedAttendees.length > 0 ? declinedAttendees.join('\n') : 'No one', inline: false }
        );

        const row = new ActionRowBuilder()
            .addComponents(
                new ButtonBuilder()
                    .setCustomId(`rsvp_accept_${eventId}`)
                    .setLabel('Accept ✅')
                    .setStyle(ButtonStyle.Success),
                new ButtonBuilder()
                    .setCustomId(`rsvp_tentative_${eventId}`)
                    .setLabel('Tentative 🤔')
                    .setStyle(ButtonStyle.Primary),
                new ButtonBuilder()
                    .setCustomId(`rsvp_decline_${eventId}`)
                    .setLabel('Decline ❌')
                    .setStyle(ButtonStyle.Danger),
                // New: Add Edit Event button
                new ButtonBuilder()
                    .setCustomId(`edit_event_${eventId}`)
                    .setLabel('Edit Event �')
                    .setStyle(ButtonStyle.Secondary),
                new ButtonBuilder()
                    .setCustomId(`delete_event_${eventId}`) // New: Delete button
                    .setLabel('Delete Event 🗑️')
                    .setStyle(ButtonStyle.Danger)
            );

        await eventMessage.edit({ embeds: [updatedEmbed], components: [row] });
        writeToLog(`Roster for event "${event.title}" (ID: ${eventId}) updated.`);

    } catch (error) {
        console.error(`Failed to update roster embed for event ${eventId}:`, error);
        writeToLog(`Failed to update roster embed for event ${eventId}: ${error.message}`);
    }
};

/**
 * Schedules the opening of an event discussion thread.
 * If the scheduled time is in the past, it attempts to open the thread immediately.
 * @param {string} eventId - The ID of the event.
 * @param {object} eventDetails - The details of the event.
 * @param {object} guild - The Discord Guild object where the event is created.
 */
const scheduleThreadOpening = (eventId, eventDetails, guild) => {
    // Parse event date and time as UTC
    const eventDateTime = moment.utc(`${eventDetails.date} ${eventDetails.startTime}`, 'DD-MM-YYYY HH:mm');
    const openTime = moment.utc(eventDateTime).subtract(eventDetails.threadOpenHoursBefore, 'hours');
    const now = moment.utc(); // Get current UTC time

    const delay = Math.max(0, openTime.diff(now));

    writeToLog(`Scheduling thread opening for event ${eventId} in ${delay / 1000} seconds (at ${openTime.format('YYYY-MM-DD HH:mm:ss')} UTC)`);

    setTimeout(async () => {
        try {
            // Fetch the original event message. This call can fail if the message was deleted.
            let eventMessage;
            try {
                const eventChannel = guild.channels.cache.get(eventDetails.channelId);
                if (!eventChannel) {
                    writeToLog(`Failed to open thread for event ${eventId}: Original event channel ${eventDetails.channelId} not found.`);
                    return; // Exit if channel isn't found
                }
                eventMessage = await eventChannel.messages.fetch(eventDetails.messageId);
            } catch (fetchError) {
                if (fetchError.code === 10008) { // DiscordAPIError[10008]: Unknown Message
                    writeToLog(`Warning: Original event message ${eventDetails.messageId} for event ${eventId} not found (DiscordAPIError 10008). Proceeding to create thread without linking to it.`);
                    // We can proceed without the original message for thread creation in the discussion channel
                } else {
                    console.error(`Error fetching original event message for event ${eventId}:`, fetchError);
                    writeToLog(`Error fetching original event message for event ${eventId}: ${fetchError.message}`);
                    return; // Exit on other fetch errors
                }
            }


            // NEW: Get the designated discussion channel for threads
            const discussionChannel = guild.channels.cache.get(DISCUSSION_CHANNEL_ID);
            if (!discussionChannel) {
                writeToLog(`Failed to open thread for event ${eventId}: Designated discussion channel ${DISCUSSION_CHANNEL_ID} not found.`);
                return;
            }
            if (discussionChannel.type !== ChannelType.GuildText && discussionChannel.type !== ChannelType.PublicThread) { // Ensure it's a text channel capable of threads
                writeToLog(`Failed to open thread for event ${eventId}: Designated discussion channel ${DISCUSSION_CHANNEL_ID} is not a valid text or public thread channel type.`);
                return;
            }

            writeToLog(`[scheduleThreadOpening] Attempting to create thread for event ${eventId} in discussion channel ${DISCUSSION_CHANNEL_ID}.`);
            const thread = await discussionChannel.threads.create({ // Create thread in the specific channel
                name: `${eventDetails.title} Discussion`,
                autoArchiveDuration: 60,
                type: ChannelType.PublicThread,
                // You can link to the original message if desired, but this creates a standalone thread in the new channel
                // startMessage: eventMessage.id, // This would attach it to the event message, but still appear under this channel ID in the list
            });
            writeToLog(`[scheduleThreadOpening] Successfully created thread for event ${eventId}. New thread ID: ${thread.id} in channel ${DISCUSSION_CHANNEL_ID}`);


            events[eventId].threadId = thread.id;
            events[eventId].threadOpenedAt = moment.utc().toISOString(); // Store as UTC ISO string
            // Update PostgreSQL with thread details
            await pgPool.query(
                `UPDATE events SET "thread_id" = $1, "thread_opened_at" = $2, "thread_roster_message_id" = $3 WHERE id = $4`,
                [thread.id, events[eventId].threadOpenedAt, null, eventId]
            );
            writeToLog(`Thread "${eventDetails.title} Discussion" opened for event ${eventId} (Thread ID: ${thread.id})`);

            const initialThreadRosterMessage = await thread.send({ embeds: [new EmbedBuilder().setTitle('Loading Roster...')], content: 'Roster will appear here once updated.' });
            events[eventId].threadRosterMessageId = initialThreadRosterMessage.id;
            // Update PostgreSQL with thread roster message ID
            await pgPool.query(
                `UPDATE events SET "thread_roster_message_id" = $1 WHERE id = $2`,
                [initialThreadRosterMessage.id, eventId]
            );

            await updateThreadRosterMessage(eventId, guild);

            for (const attendee of events[eventId].attendees) {
                if (attendee.rsvpStatus === 'Attending') {
                    try {
                        writeToLog(`[scheduleThreadOpening] Attempting to add user ${attendee.userId} to thread ${thread.id}.`);
                        const member = await guild.members.fetch(attendee.userId);
                        if (member) {
                            await thread.members.add(member.id);
                            writeToLog(`Added ${member.user.tag} to thread ${thread.id}`);
                        }
                    } catch (addError) {
                        console.error(`Failed to add user ${attendee.userId} to thread ${thread.id}:`, addError);
                        writeToLog(`Failed to add user ${attendee.userId} to thread ${thread.id}: ${addError.message}`);
                    }
                }
            }
            await thread.send(`Discussion for event "${eventDetails.title}" has started! All accepted participants have been automatically added.`);

            scheduleThreadDeletion(eventId, eventDetails, thread.id, guild);

        } catch (threadError) {
                console.error(`Error during scheduled thread opening for event ${eventId}:`, threadError);
                writeToLog(`Error during scheduled thread opening for event ${eventId}: ${threadError.message}`);
        }
    }, delay);
};

/**
 * Schedules the deletion of an event discussion thread.
 * The thread is deleted at 00:01 the day after the event finishes.
 * @param {string} eventId - The ID of the event.
 * @param {object} eventDetails - The details of the event.
 * @param {string} threadId - The ID of the discussion thread.
 * @param {object} guild - The Discord Guild object where the event is created.
 */
const scheduleThreadDeletion = (eventId, eventDetails, threadId, guild) => {
    // Parse event end date and time as UTC
    const eventEndDateTime = moment.utc(`${eventDetails.date} ${eventDetails.endTime}`, 'DD-MM-YYYY HH:mm');
    // Calculate deletion time based on UTC
    const deleteTime = moment.utc(eventEndDateTime).add(1, 'day').startOf('day').add(1, 'minute');
    const now = moment.utc(); // Get current UTC time

    const delay = Math.max(0, deleteTime.diff(now));

    writeToLog(`Scheduling thread deletion for event ${eventId} in ${delay / 1000} seconds (at ${deleteTime.format('YYYY-MM-DD HH:mm:ss')} UTC)`);

    setTimeout(async () => {
        try {
            const thread = guild.channels.cache.get(threadId);
            if (thread && thread.isThread()) {
                await thread.delete();
                events[eventId].threadId = null;
                events[eventId].threadOpenedAt = null;
                events[eventId].threadRosterMessageId = null;
                // Update PostgreSQL
                await pgPool.query(
                    `UPDATE events SET "thread_id" = NULL, "thread_opened_at" = NULL, "thread_roster_message_id" = NULL WHERE id = $1`,
                    [eventId]
                );
                writeToLog(`Thread ${threadId} for event ${eventId} deleted.`);
            } else {
                writeToLog(`Failed to delete thread for event ${eventId}: Thread ${threadId} not found or not a thread.`);
            }
        } catch (deleteError) {
            console.error(`Error during scheduled thread deletion for event ${eventId}:`, deleteError);
            writeToLog(`Error during scheduled thread deletion for event ${eventId}: ${deleteError.message}`);
        }
    }, delay);
};


/**
 * Handles the creation of a new event.
 * @param {object} channel - The Discord channel where the command was issued.
 * @param {string} title - The title of the event.
 * @param {string} date - The date of the event (DD-MM-YYYY).
 * @param {string} startTime - The start time of the event (HH:MM).
 * @param {string} endTime - The end time of the event (HH:MM).
 * @param {string[]} restrictedRoleIds - Array of role IDs that can access this event.
 * @param {object} interaction - The Discord interaction object.
 * @param {object} guild - The Discord Guild object.
 * @param {number} threadOpenHoursBefore - Hours before event start to open discussion thread.
 */
const handleCreateEvent = async (channel, title, date, startTime, endTime, description, restrictedRoleIds, interaction, guild, threadOpenHoursBefore) => {
    if (!channel) {
        if (!interaction.replied && !interaction.deferred) {
            await interaction.reply({ content: 'Could not determine the channel to send the event message. Please ensure the bot has "View Channel" and "Send Messages" permissions in this channel.', flags: [MessageFlags.Ephemeral] });
        } else {
            await interaction.followUp({ content: 'Could not determine the channel to send the event message. Please ensure the bot has "View Channel" and "Send Messages" permissions in this channel.', flags: [MessageFlags.Ephemeral] });
        }
        writeToLog(`Failed to create event "${title}" - Channel object was null or undefined.`);
        return;
    }

    // Generate a unique UUID for the event ID
    const eventId = crypto.randomUUID();
    
    // There's no longer a need to check for existing events by title/date/time
    // because UUIDs are virtually guaranteed to be unique.

    // Define all roles and their nested classes/emojis directly here
    const defaultPrimaryRoles = [
        { primaryRole: 'Commander', emoji: '👑', classes: [] },
        { primaryRole: 'Infantry', emoji: '🛡️',
            classes: [
                { className: 'Anti-Tank', emoji: '💥' },
                { className: 'Assault', emoji: '🏃' },
                { className: 'Automatic Rifleman', emoji: '💨' },
                { className: 'Engineer', emoji: '🛠️' },
                { className: 'Machine Gunner', emoji: '🔫' },
                { className: 'Medic', emoji: '🩹' },
                { className: 'Officer', emoji: '🌟' }, // Officer is here, but will be conditionally added to menu
                { className: 'Rifleman', emoji: '🎯' },
                { className: 'Support', emoji: '📦' },
            ]
        },
        { primaryRole: 'Armour', emoji: '🪖',
            classes: [
                { className: 'Tank Commander', emoji: '🪖' }, // Assuming a different emoji for clarity
                { className: 'Crewman', emoji: '🔧' },
            ]
        },
        { primaryRole: 'Recon', emoji: '🔭', classes: [] },
    ];

    const newEventData = {
        id: eventId, // Use the generated UUID as the primary key
        title,
        date,
        startTime,
        endTime,
        description,
        restrictedRoles: restrictedRoleIds,
        attendees: [], // Will be JSONB
        roles: defaultPrimaryRoles, // Will be JSONB
        threadOpenHoursBefore: threadOpenHoursBefore,
        channelId: channel.id,
        messageId: null, // Will be updated after message is sent
        threadId: null,
        threadOpenedAt: null,
        threadRosterMessageId: null,
        creatorId: interaction.user.id,
    };

    writeToLog(`[handleCreateEvent] Attempting to insert event with threadOpenHoursBefore: ${newEventData.threadOpenHoursBefore}`);


    try {
        // Insert event into PostgreSQL
        await pgPool.query(
            `INSERT INTO events (id, title, date, start_time, end_time, description, restricted_roles, attendees, roles, thread_open_hours_before, channel_id, message_id, thread_id, thread_opened_at, thread_roster_message_id, creator_id)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)`,
            [
                newEventData.id,
                newEventData.title,
                newEventData.date,
                newEventData.startTime,
                newEventData.endTime,
                newEventData.description,
                JSON.stringify(newEventData.restrictedRoles), // Store arrays as JSON strings
                JSON.stringify(newEventData.attendees),     // Store arrays as JSON strings
                JSON.stringify(newEventData.roles),         // Store arrays as JSON strings
                newEventData.threadOpenHoursBefore,
                newEventData.channelId,
                newEventData.messageId,
                newEventData.threadId,
                newEventData.threadOpenedAt,
                newEventData.threadRosterMessageId,
                newEventData.creatorId
            ]
        );
        writeToLog(`Event "${title}" (ID: ${eventId}) added to PostgreSQL.`);

        // Add to in-memory cache manually after successful DB insert
        events[eventId] = newEventData;

        const embed = new EmbedBuilder()
            .setTitle(`Event: ${newEventData.title}`)
            .setDescription(newEventData.description)
            .addFields(
                { name: 'Date', value: moment(newEventData.date, 'DD-MM-YYYY').format('DD-MM-YYYY') },
                { name: 'Time', value: `${newEventData.startTime} - ${newEventData.endTime} (24h format)` }
            );

        if (newEventData.restrictedRoles && newEventData.restrictedRoles.length > 0) {
            const roleMentions = newEventData.restrictedRoles.map(id => `<@&${id}>`).join(', ');
            embed.addFields({ name: 'Restricted To Roles', value: roleMentions, inline: false });
        }

        if (newEventData.threadOpenHoursBefore > 0) {
            const openTimeMoment = moment(`${newEventData.date} ${newEventData.startTime}`, 'DD-MM-YYYY HH:mm').subtract(newEventData.threadOpenHoursBefore, 'hours');
            embed.addFields({ name: 'Discussion Thread Opens', value: `**${openTimeMoment.format('DD-MM-YYYY HH:mm')}** (${openTimeMoment.fromNow()})`, inline: false });
        } else {
            embed.addFields({ name: 'Discussion Thread', value: `Will open at event start time.`, inline: false });
        }

        const row = new ActionRowBuilder()
            .addComponents(
                new ButtonBuilder()
                    .setCustomId(`rsvp_accept_${eventId}`)
                    .setLabel('Accept ✅')
                    .setStyle(ButtonStyle.Success),
                new ButtonBuilder()
                    .setCustomId(`rsvp_tentative_${eventId}`)
                    .setLabel('Tentative 🤔')
                    .setStyle(ButtonStyle.Primary),
                new ButtonBuilder()
                    .setCustomId(`rsvp_decline_${eventId}`)
                    .setLabel('Decline ❌')
                    .setStyle(ButtonStyle.Danger),
                // New: Add Edit Event button
                new ButtonBuilder()
                    .setCustomId(`edit_event_${eventId}`)
                    .setLabel('Edit Event 📝')
                    .setStyle(ButtonStyle.Secondary),
                new ButtonBuilder()
                    .setCustomId(`delete_event_${eventId}`) // New: Delete button
                    .setLabel('Delete Event 🗑️')
                    .setStyle(ButtonStyle.Danger)
            );

        let eventMessage;
        if (interaction.deferred || interaction.replied) {
            eventMessage = await interaction.editReply({
                embeds: [embed],
                components: [row]
            });
        } else {
            eventMessage = await interaction.followUp({
                embeds: [embed],
                components: [row]
            });
        }
        writeToLog(`[handleCreateEvent] Successfully sent event message for event: ${title}. Message ID: ${eventMessage.id}`);

        // Update PostgreSQL with the messageId
        await pgPool.query(`UPDATE events SET message_id = $1 WHERE id = $2`, [eventMessage.id, eventId]);
        events[eventId].messageId = eventMessage.id; // Update in-memory cache
        writeToLog(`PostgreSQL updated with messageId for event "${title}" (ID: ${eventId}).`);

        await updateEventRosterEmbed(eventId, guild);
        writeToLog(`Scheduling thread opening for event ${eventId}.`);
        scheduleThreadOpening(eventId, events[eventId], guild);
        writeToLog(`Event "${title}" fully set up (scheduling complete).`);

    } catch (sendError) {
        console.error(`Failed to create event in Discord or DB:`, sendError);
        writeToLog(`Failed to create event in Discord or DB: ${sendError.message}`);
        try {
            if (!interaction.replied) {
                await interaction.followUp({ content: `An error occurred while posting the main event message. Please check bot permissions. Error: ${sendError.message}`, flags: [MessageFlags.Ephemeral] });
            } else if (interaction.deferred) {
                 await interaction.followUp({ content: `An error occurred while finalizing the event message. Please check bot permissions. Error: ${sendError.message}`, flags: [MessageFlags.Ephemeral] });
            }
            // If an error occurs after inserting into DB but before sending message, consider deleting from DB
            await pgPool.query(`DELETE FROM events WHERE id = $1`, [eventId]);
            delete events[eventId]; // Remove from cache
            writeToLog(`Cleaned up partially created event ${eventId} from PostgreSQL due to error.`);
        } catch (fallbackError) {
            console.error(`Failed to send fallback error message or clean up DB after main message failed: ${fallbackError.message}`);
            writeToLog(`Failed to send fallback error message or clean up DB after main message failed: ${fallbackError.message}`);
        }
    }
};

/**
 * Handles RSVP status updates for a user for a given event.
 * @param {string} eventId - The ID of the event.
 * @param {string} userId - The ID of the user whose RSVP status is being updated.
 * @param {string} rawStatusFromButton - The raw status string from the button customId (e.g., 'accept', 'tentative', 'decline').
 * @param {object} guild - The Discord Guild object.
 * @param {object} interaction - The Discord interaction object, for followUp.
 */
const handleRSVP = async (eventId, userId, rawStatusFromButton, guild, interaction) => {
    // Fetch event from DB to ensure it's up-to-date
    let event;
    try {
        const res = await pgPool.query(`SELECT * FROM events WHERE id = $1`, [eventId]);
        if (res.rows.length === 0) {
            await interaction.followUp({ content: 'Event not found! Please use a valid Event ID.', flags: [MessageFlags.Ephemeral] });
            writeToLog(`Attempted RSVP for non-existent event: ${eventId}`);
            return;
        }
        event = {
            ...res.rows[0],
            restrictedRoles: res.rows[0].restricted_roles, // Map snake_case to camelCase
            threadOpenHoursBefore: res.rows[0].thread_open_hours_before,
            channelId: res.rows[0].channel_id,
            messageId: res.rows[0].message_id,
            threadId: res.rows[0].thread_id,
            threadOpenedAt: res.rows[0].thread_opened_at,
            threadRosterMessageId: res.rows[0].thread_roster_message_id,
            creatorId: res.rows[0].creator_id,
            attendees: res.rows[0].attendees, // JSONB comes out as JS object
            roles: res.rows[0].roles // JSONB comes out as JS object
        };
        events[eventId] = event; // Update in-memory cache
    } catch (dbError) {
        console.error(`Error fetching event ${eventId} for RSVP:`, dbError);
        writeToLog(`Error fetching event ${eventId} for RSVP: ${dbError.message}`);
        await interaction.followUp({ content: 'An error occurred while fetching event details. Please try again.', flags: [MessageFlags.Ephemeral] });
        return;
    }

    const member = await guild.members.fetch(userId);

    if (event.restrictedRoles && event.restrictedRoles.length > 0) {
        const hasRequiredRole = event.restrictedRoles.some(roleId => member.roles.cache.has(roleId));
        if (!hasRequiredRole) {
            await interaction.followUp({ content: `You do not have the required role(s) to RSVP for this event. Required roles: ${event.restrictedRoles.map(id => `<@&${id}>`).join(', ')}`, flags: [MessageFlags.Ephemeral] });
            writeToLog(`User ${userId} attempted to RSVP for event "${event.title}" but lacks required roles.`);
            return;
        }
    }

    // --- Start: Fix for duplicate declined entry ---
    let attendeeIndex = event.attendees.findIndex(a => a.userId === userId);
    let currentAttendees = [...event.attendees]; // Create a mutable copy of the array

    let attendee;
    if (attendeeIndex === -1) {
        // If it's a new attendee, create and push it to the currentAttendees array
        attendee = { userId, rsvpStatus: null, primaryRole: null, className: null, emoji: null };
        currentAttendees.push(attendee);
        attendeeIndex = currentAttendees.length - 1; // Update index to the newly added attendee
        writeToLog(`New attendee ${userId} added to event "${event.title}".`);
    } else {
        // If attendee exists, get a reference to the existing object within the currentAttendees copy
        attendee = currentAttendees[attendeeIndex];
    }
    // --- End: Fix for duplicate declined entry ---

    writeToLog(`[handleRSVP] Before status update - User ${userId} raw RSVP: ${rawStatusFromButton}. Attendee: ${JSON.stringify(attendee)}`);

    let newRsvpStatus;
    switch (rawStatusFromButton.toLowerCase()) {
        case 'accept':
            newRsvpStatus = 'Attending';
            break;
        case 'tentative':
            newRsvpStatus = 'Tentative';
            break;
        case 'decline':
            newRsvpStatus = 'Declined';
            break;
        default:
            writeToLog(`[handleRSVP] Unknown RSVP status received: ${rawStatusFromButton} for user ${userId}`);
            return;
    }

    attendee.rsvpStatus = newRsvpStatus;

    if (newRsvpStatus === 'Tentative' || newRsvpStatus === 'Declined') {
        if (attendee.primaryRole !== null || attendee.className !== null) {
            writeToLog(`User ${userId} changed RSVP to ${newRsvpStatus}, clearing previous role and class: ${attendee.primaryRole} - ${attendee.className}`);
            attendee.primaryRole = null;
            attendee.className = null;
            attendee.emoji = null;
        }
        await interaction.deleteReply().catch(error => writeToLog(`Failed to delete ephemeral reply for user ${userId}: ${error.message}`));
        writeToLog(`User ${userId} updated RSVP status to "${newRsvpStatus}" for event "${event.title}".`);

    } else if (newRsvpStatus === 'Attending') {
        let rolesForPrimarySelection = event.roles.map(role => {
            let addRole = true;
            writeToLog(`[handleRSVP] Checking primary role "${role.primaryRole}" for user ${userId}.`);
            // Corrected logic for Commander role restriction
            if (role.primaryRole === 'Commander') {
                if (CMDR_CERTIFIED_ROLE_ID && member.roles.cache.has(CMDR_CERTIFIED_ROLE_ID)) {
                    writeToLog(`[handleRSVP] User ${userId} has CMDR_CERTIFIED_ROLE_ID (${CMDR_CERTIFIED_ROLE_ID}), allowing Commander.`);
                } else if (CMDR_CERTIFIED_ROLE_ID && !member.roles.cache.has(CMDR_CERTIFIED_ROLE_ID)) {
                    addRole = false;
                    writeToLog(`[handleRSVP] User ${userId} does not have CMDR_CERTIFIED_ROLE_ID (${CMDR_CERTIFIED_ROLE_ID}), filtering out Commander.`);
                } else { // CMDR_CERTIFIED_ROLE_ID is not configured (empty or undefined)
                    writeToLog(`[handleRSVP] CMDR_CERTIFIED_ROLE_ID is not configured, allowing Commander role by default.`);
                }
            }
            // Corrected logic for Recon role restriction
            if (role.primaryRole === 'Recon') {
                if (RECON_CERTIFIED_ROLE_ID && member.roles.cache.has(RECON_CERTIFIED_ROLE_ID)) {
                    writeToLog(`[handleRSVP] User ${userId} has RECON_CERTIFIED_ROLE_ID (${RECON_CERTIFIED_ROLE_ID}), allowing Recon.`);
                } else if (RECON_CERTIFIED_ROLE_ID && !member.roles.cache.has(RECON_CERTIFIED_ROLE_ID)) {
                    addRole = false;
                    writeToLog(`[handleRSVP] User ${userId} does not have RECON_CERTIFIED_ROLE_ID (${RECON_CERTIFIED_ROLE_ID}), filtering out Recon.`);
                } else { // RECON_CERTIFIED_ROLE_ID is not configured (empty or undefined)
                    writeToLog(`[handleRSVP] RECON_CERTIFIED_ROLE_ID is not configured, allowing Recon role by default.`);
                }
            }
            return addRole ? new StringSelectMenuOptionBuilder()
                .setLabel(`${role.primaryRole} ${role.emoji}`)
                .setValue(role.primaryRole) : null;
        }).filter(Boolean);

        writeToLog(`[handleRSVP] Final rolesForPrimarySelection for user ${userId}: ${JSON.stringify(rolesForPrimarySelection.map(opt => opt.data.value))}`);

        if (!attendee.primaryRole) { // This check ensures we only ask for primary role once.
            if (rolesForPrimarySelection.length > 0) {
                const selectRoleMenu = new ActionRowBuilder()
                    .addComponents(
                        new StringSelectMenuBuilder()
                            .setCustomId(`select_role_${eventId}`)
                            .setPlaceholder('Choose your primary role...')
                            .addOptions(rolesForPrimarySelection),
                    );
                await interaction.followUp({ content: `Your RSVP for event "${event.title}" is **Accepted**! Now, please select your primary role:`, components: [selectRoleMenu], flags: [MessageFlags.Ephemeral] });
                writeToLog(`User ${userId} accepted event "${event.title}" and prompted for primary role selection.`);
            } else {
                await interaction.followUp({ content: `You accepted for event "${event.title}", but no primary roles are available for you to select. Your RSVP is confirmed!`, components: [], flags: [MessageFlags.Ephemeral] });
                writeToLog(`User ${userId} accepted but no primary roles were available.`);

                try {
                    const dmChannel = await member.user.createDM();
                    await dmChannel.send(`For event "${event.title}", you have successfully accepted. No primary role was selected as none were available for you.`);
                    writeToLog(`Sent DM to ${member.user.tag} confirming RSVP (no role) for event "${event.title}".`);
                } catch (dmError) {
                    console.error(`Failed to send DM to user ${member.user.tag} after no primary roles available: ${dmError.message}`);
                    writeToLog(`Failed to send DM to user ${member.user.tag} after no primary roles available: ${dmError.message}`);
                }
            }
        } else {
            // If they already have a primary role, confirm and update roster.
            await interaction.editReply({ content: `Your RSVP for event "${event.title}" is confirmed as **${attendee.primaryRole}${attendee.className ? ' - ' + attendee.className : ''}**!`, components: [] }).catch(error => writeToLog(`Failed to edit ephemeral reply for user ${userId}: ${error.message}`));
            writeToLog(`User ${userId} updated RSVP status to "Attending" for event "${event.title}". Role: ${attendee.primaryRole}, Class: ${attendee.className}.`);
        }
    }

    // Update PostgreSQL with the modified attendees array (currentAttendees now reflects all changes)
    try {
        await pgPool.query(
            `UPDATE events SET attendees = $1 WHERE id = $2`,
            [JSON.stringify(currentAttendees), eventId]
        );
        events[eventId].attendees = currentAttendees; // Update in-memory cache
        writeToLog(`PostgreSQL updated with attendee ${userId} for event ${eventId}. Current attendees in cache: ${JSON.stringify(events[eventId].attendees.map(a => a.userId + ':' + a.rsvpStatus + ':' + a.primaryRole + ':' + a.className + ':' + a.emoji))}`);
    } catch (pgError) {
        console.error(`Failed to update attendee ${userId} in PostgreSQL for event ${eventId}:`, pgError);
        writeToLog(`Failed to update attendee ${userId} in PostgreSQL for event ${eventId}: ${pgError.message}`);
    }


    if (event.threadId && event.threadOpenedAt) {
        try {
            const thread = guild.channels.cache.get(event.threadId);
            if (thread && thread.isThread()) {
                if (newRsvpStatus === 'Attending') {
                    writeToLog(`[handleRSVP] Attempting to add user ${userId} to thread ${thread.id}.`);
                    const memberInThread = await thread.members.fetch(userId).catch(() => null); // Check if already in thread
                    if (!memberInThread) { // Only add if not already in thread
                        await thread.members.add(userId);
                        writeToLog(`[handleRSVP] Successfully added user ${userId} to thread ${thread.id}.`);
                    } else {
                        writeToLog(`[handleRSVP] User ${userId} already in thread ${thread.id}, no re-add needed.`);
                    }
                } else {
                    writeToLog(`[handleRSVP] Attempting to remove user ${userId} from thread ${thread.id}.`);
                    const threadMember = await thread.members.fetch(userId).catch(() => null);
                    if (threadMember) {
                        await thread.members.remove(userId);
                        writeToLog(`[handleRSVP] Successfully removed user ${userId} from thread ${thread.id}.`);
                    } else {
                        writeToLog(`[handleRSVP] User ${userId} not found in thread ${thread.id}, no removal needed.`);
                    }
                }
            } else {
                writeToLog(`[handleRSVP] Thread ${event.threadId} not found or not a thread for user ${userId}.`);
            }
        } catch (threadMemberError) {
            console.error(`Failed to update user ${userId} in thread ${event.threadId}:`, threadMemberError);
            writeToLog(`Failed to update user ${userId} in thread ${thread.id}: ${threadMemberError.message}`);
        }
    }

    writeToLog(`[handleRSVP] After status update, calling roster updates. Event ${eventId} attendees: ${JSON.stringify(events[eventId].attendees.map(a => `${a.userId}:${a.rsvpStatus}:${a.primaryRole}:${a.className}:${a.emoji}`))}`);
    await updateEventRosterEmbed(eventId, guild);
    if (event.threadId && event.threadRosterMessageId) {
        await updateThreadRosterMessage(eventId, guild);
    }
};


// --- Slash Command Definitions ---
const commands = [
    {
        name: 'newevent', // New command to trigger the modal
        description: 'Opens a form to create a new event.',
    },
];

const registerSlashCommands = async () => {
    const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
    const CLIENT_ID = process.env.CLIENT_ID;
    const GUILD_ID = process.env.GUILD_ID; // Ensure GUILD_ID is also fetched if registering guild commands

    if (!CLIENT_ID) {
        console.error('CLIENT_ID is not defined in .env! Cannot register commands.');
        writeToLog(`CLIENT_ID is not defined in .env! Cannot register commands.`);
        return;
    }

    try {
        console.log('Started refreshing application (/) commands.');
        writeToLog(`Started refreshing application (/) commands.`);

        if (GUILD_ID) {
            await rest.put(Routes.applicationGuildCommands(CLIENT_ID, GUILD_ID), { body: commands });
            console.log(`Successfully reloaded application (/) commands for guild ${GUILD_ID}.`);
            writeToLog(`Successfully reloaded application (/) commands for guild ${GUILD_ID}.`);
        } else {
            await rest.put(Routes.applicationCommands(CLIENT_ID), { body: commands });
            console.log('Successfully reloaded application (/) commands globally.');
            writeToLog(`Successfully reloaded application (/) commands globally.`);
        }

    } catch (error) {
        console.error('Failed to register slash commands:', error);
        writeToLog(`Failed to register slash commands: ${error.message}`);
    }
};


// --- Event Listeners for Discord Client ---

client.on('interactionCreate', async (interaction) => {
    // Safely log customId and commandName to prevent crashes on interaction types that don't have them
    const customIdLog = interaction.isMessageComponent() ? interaction.customId : 'N/A';
    const commandNameLog = interaction.isChatInputCommand() ? interaction.commandName : 'N/A';
    writeToLog(`Received interaction: Type ${interaction.type}, CustomId: ${customIdLog}, CommandName: ${commandNameLog}`);

    const { customId, user } = interaction; // Destructure common properties
    const guild = interaction.guild; // Get guild directly for safety check

    // Add this check at the very beginning of the interactionCreate listener
    if (!guild) {
        writeToLog(`Interaction ${interaction.id} received outside a guild context or guild is null/undefined. User: ${user.tag}`);
        if (interaction.isRepliable()) {
            await interaction.reply({ content: 'This command can only be used in a Discord server (guild).', flags: [MessageFlags.Ephemeral] });
        }
        return; // Exit early
    }

    if (interaction.isButton()) {
        if (customId.startsWith('rsvp_')) {
            await interaction.deferReply({ flags: [MessageFlags.Ephemeral] });
            writeToLog(`Interaction deferred for button click: ${customId}`);
        } else if (customId.startsWith('edit_event_')) {
            writeToLog(`Received edit button click for event: ${customId}`);
            
            const eventId = customId.substring('edit_event_'.length);
            let eventToEdit;

            try {
                const res = await pgPool.query(`SELECT * FROM events WHERE id = $1`, [eventId]);
                if (res.rows.length === 0) {
                    writeToLog(`Error: Event ${eventId} not found in DB when user ${user.id} tried to edit.`);
                    // If event not found, reply with an error.
                    return await interaction.reply({ content: 'Error: Event not found in database. It might have been deleted. Please create a new event.', flags: [MessageFlags.Ephemeral] });
                }
                eventToEdit = {
                    ...res.rows[0],
                    // Explicitly map snake_case from DB to camelCase for use in Discord.js objects
                    startTime: res.rows[0].start_time,
                    endTime: res.rows[0].end_time,
                    restrictedRoles: res.rows[0].restricted_roles,
                    threadOpenHoursBefore: res.rows[0].thread_open_hours_before,
                    channelId: res.rows[0].channel_id,
                    messageId: res.rows[0].message_id,
                    threadId: res.rows[0].thread_id,
                    threadOpenedAt: res.rows[0].thread_opened_at,
                    threadRosterMessageId: res.rows[0].thread_roster_message_id,
                    creatorId: res.rows[0].creator_id,
                    attendees: res.rows[0].attendees,
                    roles: res.rows[0].roles
                };
                events[eventId] = eventToEdit; // Update in-memory cache
            } catch (dbError) {
                console.error(`Error fetching event ${eventId} for edit:`, dbError);
                writeToLog(`Error fetching event ${eventId} for edit: ${dbError.message}`);
                // If DB error, reply with an error.
                return await interaction.reply({ content: 'An error occurred while fetching event details for editing. Please try again.', flags: [MessageFlags.Ephemeral] });
            }

            const member = await guild.members.fetch(user.id);

            if (user.id !== eventToEdit.creatorId && (!DELETE_EVENT_ROLE_ID || !member.roles.cache.has(DELETE_EVENT_ROLE_ID))) {
                writeToLog(`User ${user.id} attempted to edit event ${eventId} but is not the creator (${eventToEdit.creatorId}) and does not have the configured delete role.`);
                // If permission denied, reply with an error.
                return await interaction.reply({ content: 'You do not have permission to edit this event.', flags: [MessageFlags.Ephemeral] });
            }

            const modal = new ModalBuilder()
                .setCustomId(`editEventModal_${eventId}`)
                .setTitle(`Edit Event: ${eventToEdit.title}`);

            const titleInput = new TextInputBuilder()
                .setCustomId('editTitleInput')
                .setLabel('Event Title')
                .setStyle(TextInputStyle.Short)
                .setRequired(true)
                .setValue(eventToEdit.title || ''); // Add fallback

            const dateInput = new TextInputBuilder()
                .setCustomId('editDateInput')
                .setLabel('Event Date (DD-MM-YYYY)')
                .setPlaceholder('e.g., 22-06-2025')
                .setStyle(TextInputStyle.Short)
                .setRequired(true)
                .setValue(eventToEdit.date || ''); // Add fallback

            const startTimeInput = new TextInputBuilder()
                .setCustomId('editStartTimeInput')
                .setLabel('Start Time (HH:MM, 24h format)')
                .setPlaceholder('e.g., 19:00')
                .setStyle(TextInputStyle.Short)
                .setRequired(true)
                .setValue(eventToEdit.startTime || ''); // This will now correctly pull from mapped startTime

            const endTimeInput = new TextInputBuilder()
                .setCustomId('editEndTimeInput')
                .setLabel('End Time (HH:MM, 24h format)')
                .setPlaceholder('e.g., 22:00')
                .setStyle(TextInputStyle.Short)
                .setRequired(true)
                .setValue(eventToEdit.endTime || ''); // This will now correctly pull from mapped endTime

            const descriptionInput = new TextInputBuilder()
                .setCustomId('editDescriptionInput')
                .setLabel('Event Description')
                .setStyle(TextInputStyle.Paragraph)
                .setRequired(true)
                .setValue(eventToEdit.description || ''); // Add fallback

            modal.addComponents(
                new ActionRowBuilder().addComponents(titleInput),
                new ActionRowBuilder().addComponents(dateInput),
                new ActionRowBuilder().addComponents(startTimeInput),
                new ActionRowBuilder().addComponents(endTimeInput),
                new ActionRowBuilder().addComponents(descriptionInput),
            );

            try {
                // showModal implicitly replies to the interaction.
                await interaction.showModal(modal);
                writeToLog(`Edit modal for event ${eventId} shown to user ${user.tag}.`);
            } catch (modalError) {
                console.error(`Failed to show edit event modal for user ${user.id} and event ${eventId}:`, modalError);
                writeToLog(`Failed to show edit event modal for user ${user.id} and event ${eventId}: ${modalError.message}`);
                // If modal fails, reply to the interaction with an error message.
                // This will be the first and only reply if showModal failed at the API level.
                await interaction.reply({ content: 'Failed to open the edit form. Please try again later or contact an admin.', flags: [MessageFlags.Ephemeral] });
            }
            return; // Return here, as showModal or interaction.reply has handled the interaction.
        } else if (customId.startsWith('delete_event_')) { // New: Delete button handler
            await interaction.deferReply({ flags: [MessageFlags.Ephemeral] });
            writeToLog(`Interaction deferred for delete button click: ${customId}`);

            const eventId = customId.substring('delete_event_'.length);
            
            // Fetch event from DB to get creatorId
            let eventToDelete;
            try {
                const res = await pgPool.query(`SELECT creator_id, message_id FROM events WHERE id = $1`, [eventId]);
                if (res.rows.length === 0) {
                    writeToLog(`Error: Event ${eventId} not found in DB when user ${user.id} tried to delete.`);
                    return await interaction.editReply({ content: 'Error: Event not found in database. It might have already been deleted or never existed.', flags: [MessageFlags.Ephemeral] });
                }
                eventToDelete = res.rows[0];
            } catch (dbError) {
                console.error(`Error fetching event ${eventId} for deletion:`, dbError);
                writeToLog(`Error fetching event ${eventId} for deletion: ${dbError.message}`);
                return await interaction.editReply({ content: 'An error occurred while fetching event details for deletion. Please try again.', flags: [MessageFlags.Ephemeral] });
            }

            const member = await guild.members.fetch(user.id);
            const isCreator = user.id === eventToDelete.creator_id;
            const hasDeleteRole = DELETE_EVENT_ROLE_ID && member.roles.cache.has(DELETE_EVENT_ROLE_ID);

            // --- Start: Added detailed logging for delete permission check ---
            writeToLog(`[DeletePermissionCheck] User ${user.id} attempting to delete event ${eventId}.`);
            writeToLog(`[DeletePermissionCheck] Event Creator ID: ${eventToDelete.creator_id}`);
            writeToLog(`[DeletePermissionCheck] Is User the Creator? ${isCreator}`);
            writeToLog(`[DeletePermissionCheck] Configured DELETE_EVENT_ROLE_ID: ${DELETE_EVENT_ROLE_ID}`);
            writeToLog(`[DeletePermissionCheck] Does User Have Delete Role? ${hasDeleteRole}`);
            // --- End: Added detailed logging for delete permission check ---

            if (!isCreator && !hasDeleteRole) {
                writeToLog(`User ${user.id} DENIED deletion for event ${eventId}: Not creator and does not have delete role.`);
                return await interaction.editReply({ content: 'You do not have permission to delete this event.', flags: [MessageFlags.Ephemeral] });
            }
            writeToLog(`User ${user.id} GRANTED deletion for event ${eventId}.`);

            // Perform deletion
            try {
                // Delete from PostgreSQL
                await pgPool.query(`DELETE FROM events WHERE id = $1`, [eventId]);
                delete events[eventId]; // Remove from in-memory cache
                writeToLog(`Event ${eventId} deleted from PostgreSQL by ${user.tag}.`);

                // Delete the original event message in Discord
                if (eventToDelete.message_id) {
                    const channel = guild.channels.cache.get(interaction.channelId); // Get current channel
                    if (channel) {
                        const messageToDelete = await channel.messages.fetch(eventToDelete.message_id).catch(() => null);
                        if (messageToDelete) {
                            await messageToDelete.delete();
                            writeToLog(`Discord message ${eventToDelete.message_id} for event ${eventId} deleted.`);
                        } else {
                            writeToLog(`Discord message ${eventToDelete.message_id} not found for event ${eventId}. Already deleted?`);
                        }
                    } else {
                        writeToLog(`Channel ${interaction.channelId} not found to delete message ${eventToDelete.message_id} for event ${eventId}.`);
                    }
                }

                await interaction.editReply({ content: 'Event and associated Discord message deleted successfully!', flags: [MessageFlags.Ephemeral] });
            } catch (deleteError) {
                console.error(`Failed to delete event ${eventId}:`, deleteError);
                writeToLog(`Failed to delete event ${eventId}: ${deleteError.message}`);
                await interaction.editReply({ content: 'An error occurred while trying to delete the event.', flags: [MessageFlags.Ephemeral] });
            }
        }
    } else if (interaction.isStringSelectMenu()) {
        await interaction.deferUpdate();
        // Use customIdLog which is safely determined at the top of the handler
        writeToLog(`Interaction deferred (update) for select menu: ${customIdLog}`);
    }

    try {
        if (interaction.isChatInputCommand()) {
            writeToLog(`Chat input command received: /${interaction.commandName}`);
            if (interaction.commandName === 'newevent') {
                writeToLog(`Attempting to show modal for /newevent command.`);
                const modal = new ModalBuilder()
                    .setCustomId('createEventModal')
                    .setTitle('Create New Event');

                const titleInput = new TextInputBuilder()
                    .setCustomId('titleInput')
                    .setLabel('Event Title')
                    .setStyle(TextInputStyle.Short)
                    .setRequired(true);

                const dateInput = new TextInputBuilder()
                    .setCustomId('dateInput')
                    .setLabel('Event Date (DD-MM-YYYY)')
                    .setPlaceholder('e.g., 22-06-2025')
                    .setStyle(TextInputStyle.Short)
                    .setRequired(true);

                const startTimeInput = new TextInputBuilder()
                    .setCustomId('startTimeInput')
                    .setLabel('Start Time (HH:MM, 24h format)')
                    .setPlaceholder('e.g., 19:00')
                    .setStyle(TextInputStyle.Short)
                    .setRequired(true);

                const endTimeInput = new TextInputBuilder()
                    .setCustomId('endTimeInput')
                    .setLabel('End Time (HH:MM, 24h format)')
                    .setPlaceholder('e.g., 22:00')
                    .setStyle(TextInputStyle.Short)
                    .setRequired(true);

                const descriptionInput = new TextInputBuilder()
                    .setCustomId('descriptionInput')
                    .setLabel('Event Description')
                    .setStyle(TextInputStyle.Paragraph)
                    .setRequired(true)
                    .setPlaceholder('Provide a detailed description for your event. Use carriage returns for new lines.');

                modal.addComponents(
                    new ActionRowBuilder().addComponents(titleInput),
                    new ActionRowBuilder().addComponents(dateInput),
                    new ActionRowBuilder().addComponents(startTimeInput),
                    new ActionRowBuilder().addComponents(endTimeInput),
                    new ActionRowBuilder().addComponents(descriptionInput),
                );

                try {
                    await interaction.showModal(modal);
                    writeToLog(`Modal "createEventModal" shown successfully by user ${interaction.user.tag}`);
                } catch (modalError) {
                    console.error(`Error showing modal for /newevent:`, modalError);
                    writeToLog(`Error showing modal for /newevent: ${modalError.message}`);
                    if (!interaction.replied && interaction.isRepliable()) {
                        await interaction.reply({ content: 'Failed to open the event creation form. Please try again later or contact an admin.', flags: [MessageFlags.Ephemeral] });
                    }
                }
                return;
            }

        } else if (interaction.isModalSubmit()) {
            if (interaction.customId === 'createEventModal') {
                await interaction.deferReply({ ephemeral: false });
                writeToLog(`Modal "createEventModal" submitted by user ${interaction.user.tag}. Deferred reply.`);

                const title = interaction.fields.getTextInputValue('titleInput');
                const date = interaction.fields.getTextInputValue('dateInput');
                const startTime = interaction.fields.getTextInputValue('startTimeInput');
                const endTime = interaction.fields.getTextInputValue('endTimeInput');
                const description = interaction.fields.getTextInputValue('descriptionInput');
                
                const threadOpenHoursBefore = 12; // This is the default for new events
                const restrictedRoleIds = [];

                await handleCreateEvent(interaction.channel, title, date, startTime, endTime, description, restrictedRoleIds, interaction, interaction.guild, threadOpenHoursBefore);
            } else if (interaction.customId.startsWith('editEventModal_')) {
                await interaction.deferReply({ ephemeral: true }); // Defer the modal submission interaction
                writeToLog(`Modal "editEventModal" submitted by user ${interaction.user.tag}. Deferred reply.`);

                const eventId = interaction.customId.substring('editEventModal_'.length);
                // Fetch from DB for freshest data
                let eventToEdit;
                try {
                    const res = await pgPool.query(`SELECT * FROM events WHERE id = $1`, [eventId]);
                    if (res.rows.length === 0) {
                        writeToLog(`Error: Original event ${eventId} not found in DB for editing by ${interaction.user.id}.`);
                        return await interaction.editReply({ content: 'Error: Original event not found in database. Please create a new event.', flags: [MessageFlags.Ephemeral] });
                    }
                    eventToEdit = {
                        ...res.rows[0],
                        restrictedRoles: res.rows[0].restricted_roles,
                        threadOpenHoursBefore: res.rows[0].thread_open_hours_before,
                        channelId: res.rows[0].channel_id,
                        messageId: res.rows[0].message_id,
                        threadId: res.rows[0].thread_id,
                        threadOpenedAt: res.rows[0].thread_opened_at,
                        threadRosterMessageId: res.rows[0].thread_roster_message_id,
                        creatorId: res.rows[0].creator_id,
                        attendees: res.rows[0].attendees,
                        roles: res.rows[0].roles
                    };
                    events[eventId] = eventToEdit; // Update in-memory cache
                } catch (dbError) {
                    console.error(`Error fetching event ${eventId} for modal submission:`, dbError);
                    writeToLog(`Error fetching event ${eventId} for modal submission: ${dbError.message}`);
                    return await interaction.editReply({ content: 'An error occurred while fetching event details. Please try again.', flags: [MessageFlags.Ephemeral] });
                }

                const member = await guild.members.fetch(interaction.user.id); // Fetch member for role check
                if (interaction.user.id !== eventToEdit.creatorId && (!DELETE_EVENT_ROLE_ID || !member.roles.cache.has(DELETE_EVENT_ROLE_ID))) {
                    writeToLog(`User ${interaction.user.id} attempted to submit edit for event ${eventId} but is not the creator (${eventToEdit.creatorId}) and does not have the configured delete role.`);
                    return await interaction.editReply({ content: 'You do not have permission to edit this event.', flags: [MessageFlags.Ephemeral] });
                }

                const newTitle = interaction.fields.getTextInputValue('editTitleInput');
                const newDate = interaction.fields.getTextInputValue('editDateInput');
                const newStartTime = interaction.fields.getTextInputValue('editStartTimeInput');
                const newEndTime = interaction.fields.getTextInputValue('editEndTimeInput');
                const newDescription = interaction.fields.getTextInputValue('editDescriptionInput');

                // Update PostgreSQL
                try {
                    await pgPool.query(
                        `UPDATE events SET title = $1, date = $2, start_time = $3, end_time = $4, description = $5 WHERE id = $6`,
                        [newTitle, newDate, newStartTime, newEndTime, newDescription, eventId]
                    );
                    writeToLog(`PostgreSQL updated for event ${eventId} by ${interaction.user.tag}.`);

                    // Update in-memory cache directly after successful DB update
                    events[eventId].title = newTitle;
                    events[eventId].date = newDate;
                    events[eventId].startTime = newStartTime;
                    events[eventId].endTime = newEndTime;
                    events[eventId].description = newDescription;

                } catch (pgError) {
                    console.error(`Failed to update event ${eventId} in PostgreSQL:`, pgError);
                    writeToLog(`Failed to update event ${eventId} in PostgreSQL: ${pgError.message}`);
                    return await interaction.editReply({ content: 'Error updating event in database.', flags: [MessageFlags.Ephemeral] });
                }
                
                await interaction.editReply({ content: 'Event details updated successfully!', components: [], embeds: [] });
                writeToLog(`Event ${eventId} details updated by ${interaction.user.tag}.`);
                
                // Manually trigger Discord message updates
                await updateEventRosterEmbed(eventId, interaction.guild);
                if (eventToEdit.threadId) {
                    await updateThreadRosterMessage(eventId, interaction.guild);
                }
            }
        } else if (interaction.isButton()) {
            const { customId, user, guild } = interaction;

            if (customId.startsWith('rsvp_')) {
                const parts = customId.split('_');
                const rawStatusFromButton = parts[1];
                const eventId = parts.slice(2).join('_');

                await handleRSVP(eventId, user.id, rawStatusFromButton, guild, interaction);
            }
        } else if (interaction.isStringSelectMenu()) {
            const { customId, values, user, guild } = interaction;

            const eventId = customId.split('_').slice(2).join('_');
            const selectedValue = values[0];

            // Fetch event from DB to ensure it's up-to-date
            let event;
            try {
                const res = await pgPool.query(`SELECT * FROM events WHERE id = $1`, [eventId]);
                if (res.rows.length === 0) {
                    await interaction.editReply({ content: 'Event not found! Could not process your selection. Please try RSVPing again or contact an admin.', components: [] });
                    writeToLog(`Error processing select menu: Event ${eventId} not found for user ${user.id}.`);
                    return;
                }
                event = {
                    ...res.rows[0],
                    restrictedRoles: res.rows[0].restricted_roles,
                    threadOpenHoursBefore: res.rows[0].thread_open_hours_before,
                    channelId: res.rows[0].channel_id,
                    messageId: res.rows[0].message_id,
                    threadId: res.rows[0].thread_id,
                    threadOpenedAt: res.rows[0].thread_opened_at,
                    threadRosterMessageId: res.rows[0].thread_roster_message_id,
                    creatorId: res.rows[0].creator_id,
                    attendees: res.rows[0].attendees, // JSONB comes out as JS object
                    roles: res.rows[0].roles // JSONB comes out as JS object
                };
                events[eventId] = event; // Update in-memory cache
            } catch (dbError) {
                console.error(`Error fetching event ${eventId} for select menu:`, dbError);
                writeToLog(`Error fetching event ${eventId} for select menu: ${dbError.message}`);
                await interaction.editReply({ content: 'An error occurred while fetching event details. Please try again.', components: [] });
                return;
            }

            // Ensure currentAttendees is defined in this scope
            let currentAttendees = [...event.attendees];
            const attendeeIndex = currentAttendees.findIndex(a => a.userId === user.id);
            let attendee;

            if (attendeeIndex === -1) {
                // This case should ideally not happen if user already RSVP'd (Accepted) to get to this menu.
                // But robustly handle by adding them, assuming "Attending".
                attendee = { userId, rsvpStatus: 'Attending', primaryRole: null, className: null, emoji: null };
                currentAttendees.push(attendee);
                writeToLog(`[select menu] New attendee ${user.id} added (via select menu, assumed Accepted) for event ${eventId}.`);
            } else {
                attendee = currentAttendees[attendeeIndex];
            }

            const member = await guild.members.fetch(user.id);

            // --- Handle Primary Role Selection ---
            if (customId.startsWith('select_role_')) {
                attendee.primaryRole = selectedValue;
                attendee.className = null;
                attendee.emoji = null; // Clear class emoji when primary role changes
                attendee.rsvpStatus = 'Attending';


                writeToLog(`[select_role] User ${user.id} selected primary role "${selectedValue}" for event "${event.title}".`);

                if (selectedValue === 'Infantry' || selectedValue === 'Armour') {
                    const primaryRoleObj = event.roles.find(r => r.primaryRole === selectedValue);
                    let classesForSelection = primaryRoleObj ? primaryRoleObj.classes : [];

                    writeToLog(`[select_role] Before class filtering for ${selectedValue} - classes: ${JSON.stringify(classesForSelection.map(c => c.className))}`);

                    if (attendee.primaryRole === 'Infantry') {
                        const isSLCertified = SL_CERTIFIED_ROLE_ID && member.roles.cache.has(SL_CERTIFIED_ROLE_ID); // Check if SL_CERTIFIED_ROLE_ID is defined
                        writeToLog(`[select_role] User ${user.id} is SL certified: ${isSLCertified} (SL_CERTIFIED_ROLE_ID: ${SL_CERTIFIED_ROLE_ID})`);
                        if (!isSLCertified) {
                            classesForSelection = classesForSelection.filter(c => c.className !== 'Officer');
                            writeToLog(`User ${user.id} is not SL certified (or role ID not configured), "Officer" class filtered out for Infantry selection.`);
                        }
                    } else if (attendee.primaryRole === 'Armour') {
                        const isTCCertified = TC_CERTIFIED_ROLE_ID && member.roles.cache.has(TC_CERTIFIED_ROLE_ID); // Check if TC_CERTIFIED_ROLE_ID is defined
                        writeToLog(`[select_role] User ${user.id} is TC certified: ${isTCCertified} (TC_CERTIFIED_ROLE_ID: ${TC_CERTIFIED_ROLE_ID})`);
                        if (!isTCCertified) {
                            classesForSelection = classesForSelection.filter(c => c.className !== 'Tank Commander');
                            writeToLog(`User ${user.id} is not TC certified (or role ID not configured), "Tank Commander" class filtered out for Armour selection.`);
                        }
                        return; // Add a return statement here to exit the function
                    }

                    writeToLog(`[select_role] After class filtering for ${selectedValue} - classes: ${JSON.stringify(classesForSelection.map(c => c.className))}`);


                    if (classesForSelection.length > 0) {
                        const selectClassMenu = new ActionRowBuilder()
                            .addComponents(
                                new StringSelectMenuBuilder()
                                    .setCustomId(`select_class_${eventId}`)
                                    .setPlaceholder(`Choose your ${attendee.primaryRole} class...`)
                                    .addOptions(
                                        classesForSelection.map(cls => new StringSelectMenuOptionBuilder()
                                            .setLabel(`${cls.className} ${cls.emoji}`)
                                            .setValue(cls.className)
                                        )
                                    ),
                            );
                        await interaction.editReply({ content: `You have selected **${selectedValue}**. Now, please select your specific class:`, components: [selectClassMenu] });
                        writeToLog(`User ${user.id} prompted for ${selectedValue} class selection for event "${event.title}".`);
                    } else {
                        // If no classes are available, the primary role emoji should be used
                        const primaryRoleObj = event.roles.find(r => r.primaryRole === selectedValue);
                        if (primaryRoleObj) attendee.emoji = primaryRoleObj.emoji; // Set primary role emoji
                        await interaction.editReply({ content: `You accepted **${attendee.primaryRole}** for event "${event.title}". No specific class was selected as none were available for you. Your RSVP is confirmed!`, components: [] });
                        writeToLog(`User ${user.id} accepted ${attendee.primaryRole} but no classes were available. RSVP confirmed without class.`);

                        try {
                            const dmChannel = await user.createDM();
                            await dmChannel.send(`For event "${event.title}", you have successfully selected **${attendee.primaryRole}** as your primary role. Your RSVP is confirmed! (No specific class was selected as none were available for you.)`);
                            writeToLog(`Sent DM to ${user.tag} confirming primary role selection (no class) for event "${event.title}".`);
                        } catch (dmError) {
                            console.error(`Failed to send DM to user ${user.tag} after no primary roles available: ${dmError.message}`);
                            writeToLog(`Failed to send DM to user ${user.tag} after no primary roles available: ${dmError.message}`);
                        }
                    }
                } else { // For Commander and Recon, which have no nested classes
                    const primaryRoleObj = event.roles.find(r => r.primaryRole === selectedValue);
                    if (primaryRoleObj) attendee.emoji = primaryRoleObj.emoji; // Set primary role emoji

                    await interaction.editReply({ content: `Your RSVP for event "${event.title}" is confirmed as **${selectedValue}**!`, components: [] });
                    writeToLog(`User ${user.id} confirmed RSVP for event "${event.title}" with primary role "${selectedValue}".`);

                    try {
                        const dmChannel = await user.createDM();
                        await dmChannel.send(`For event "${event.title}", you have successfully selected **${selectedValue}** as your primary role. Your RSVP is confirmed!`);
                        writeToLog(`Sent DM to ${user.tag} confirming primary role selection for event "${event.title}".`);
                    } catch (dmError) {
                        console.error(`Failed to send DM to user ${user.tag}: ${dmError.message}`);
                        writeToLog(`Failed to send DM to user ${user.tag}: ${dmError.message}`);
                    }
                }

            } else if (customId.startsWith('select_class_')) {
                attendee.className = selectedValue;
                attendee.rsvpStatus = 'Attending';

                const primaryRoleObj = event.roles.find(r => r.primaryRole === attendee.primaryRole);
                if (primaryRoleObj) {
                    const classObj = primaryRoleObj.classes.find(c => c.className === selectedValue);
                    if (classObj) attendee.emoji = classObj.emoji; // Set class emoji for display
                    writeToLog(`[select_class] Setting attendee emoji to ${attendee.emoji} for class ${selectedValue}.`);
                }

                await interaction.editReply({ content: `Your RSVP for event "${event.title}" is confirmed as **${attendee.primaryRole} - ${attendee.className}**!`, components: [] });
                writeToLog(`User ${user.id} confirmed RSVP for event "${event.title}" with primary role "${attendee.primaryRole}" and class "${attendee.className}".`);

                try {
                    const dmChannel = await user.createDM();
                    await dmChannel.send(`For event "${event.title}", you have successfully selected **${attendee.primaryRole} - ${attendee.className}** as your role. Your RSVP is confirmed!`);
                    writeToLog(`Sent DM to ${user.tag} confirming role and class selection for event "${event.title}".`);
                } catch (dmError) {
                    console.error(`Failed to send DM to user ${user.tag}: ${dmError.message}`);
                    writeToLog(`Failed to send DM to user ${user.tag}: ${dmError.message}`);
                }
            }
            
            // Save the updated currentAttendees array to PostgreSQL
            try {
                await pgPool.query(
                    `UPDATE events SET attendees = $1 WHERE id = $2`,
                    [JSON.stringify(currentAttendees), eventId]
                );
                events[eventId].attendees = currentAttendees; // Update in-memory cache
                writeToLog(`PostgreSQL updated with attendee ${user.id} for event ${eventId} after select menu interaction. Current attendees in cache after update: ${JSON.stringify(events[eventId].attendees.map(a => a.userId + ':' + a.rsvpStatus + ':' + a.primaryRole + ':' + a.className + ':' + a.emoji))}`);

            } catch (pgError) {
                console.error(`Failed to update attendee ${user.id} in PostgreSQL for event ${eventId} after select menu:`, pgError);
                writeToLog(`Failed to update attendee ${user.id} in PostgreSQL for event ${eventId} after select menu: ${pgError.message}`);
            }

            writeToLog(`[interactionCreate - select menu] After attendee update, calling roster updates. Event ${eventId} attendees: ${JSON.stringify(events[eventId].attendees.map(a => `${a.userId}:${a.rsvpStatus}:${a.primaryRole}:${a.className}:${a.emoji}`))}`);
            await updateEventRosterEmbed(eventId, guild);
            if (event.threadId && event.threadRosterMessageId) {
                await updateThreadRosterMessage(eventId, guild);
            }
        }
    } catch (error) {
        console.error(`Error handling interaction:`, error);
        console.trace(error);
        writeToLog(`Error handling interaction: ${error.message}`);
        if (interaction.isRepliable()) {
             if (interaction.deferred || interaction.replied) {
                await interaction.followUp({ content: 'An unexpected error occurred while processing your request! Please try again or contact an an admin.', flags: [MessageFlags.Ephemeral] }).catch(err => {
                    console.error(`Failed to send followUp error message: ${err.message}`);
                    writeToLog(`Failed to send followUp error message: ${err.message}`);
                });
            } else {
                await interaction.reply({ content: 'An unexpected error occurred!', flags: [MessageFlags.Ephemeral] }).catch(err => {
                    console.error(`Failed to send initial error reply: ${err.message}`);
                    writeToLog(`Failed to send initial error reply: ${err.message}`);
                });
            }
        } else {
            console.warn(`Interaction ${interaction.id} is not repliable, cannot send error message to user.`);
            writeToLog(`Interaction ${interaction.id} is not repliable, cannot send error message to user.`);
        }
    }
});

// New: Listen for message deletions
client.on('messageDelete', async (message) => {
    writeToLog(`Message deleted: ${message.id} in channel ${message.channelId}`);

    // Check if the deleted message was an event message
    try {
        const res = await pgPool.query(`SELECT id FROM events WHERE message_id = $1`, [message.id]);
        if (res.rows.length > 0) {
            const eventIdToDelete = res.rows[0].id;
            
            // Delete the event from PostgreSQL
            await pgPool.query(`DELETE FROM events WHERE id = $1`, [eventIdToDelete]);
            delete events[eventIdToDelete]; // Also remove from in-memory cache
            writeToLog(`Event ${eventIdToDelete} deleted from database due to message ${message.id} being deleted.`);

            // If a thread was associated, try to delete it
            const eventData = Object.values(events).find(e => e.id === eventIdToDelete);
            if (eventData && eventData.threadId) {
                const thread = message.guild.channels.cache.get(eventData.threadId);
                if (thread && thread.isThread()) {
                    await thread.delete().catch(err => {
                        console.error(`Failed to delete associated thread ${eventData.threadId}: ${err.message}`);
                        writeToLog(`Failed to delete associated thread ${eventData.threadId}: ${err.message}`);
                    });
                }
            }
        }
    } catch (error) {
        console.error(`Error handling messageDelete event for database cleanup:`, error);
        writeToLog(`Error handling messageDelete event for database cleanup: ${error.message}`);
    }
});


// Handles traditional prefix commands (e.g., "!createevent") - No changes needed here for interaction deferral issues.
client.on('messageCreate', async (message) => {
    if (message.author.bot) return;

    const args = message.content.split(' ');
    const command = args[0].toLowerCase();
    const replyMethod = message.reply.bind(message);

    if (command === '!createevent') {
        if (args.length < 6) {
            writeToLog(`Invalid !createevent command from ${message.author.id}: ${message.content}`);
            return message.reply('Usage: `!createevent <title> <YYYY-MM-DD> <HH:MM> <description> <image_url>`');
        }
        
        const title = args[1];
        const date = args[2];
        const startTime = args[3];
        const endTime = args[4];
        
        let descriptionParts = [];
        let threadOpenHoursBefore = 0;
        let restrictedRolesString = '';
        let parsingState = 'description';

        for (let i = 5; i < args.length; i++) {
            const arg = args[i];
            if (parsingState === 'description') {
                if (!isNaN(parseInt(arg)) && String(parseInt(arg)) === arg) {
                    threadOpenHoursBefore = parseInt(arg);
                    parsingState = 'threadHours';
                } else if (arg.startsWith('<@&') && arg.endsWith('>')) {
                    restrictedRolesString += arg + ' ';
                    parsingState = 'roles';
                } else {
                    descriptionParts.push(arg);
                }
            } else if (parsingState === 'threadHours') {
                if (arg.startsWith('<@&') && arg.endsWith('>')) {
                    restrictedRolesString += arg + ' ';
                    parsingState = 'roles';
                } else {
                    restrictedRolesString += arg + ' ';
                }
            } else if (parsingState === 'roles') {
                restrictedRolesString += arg + ' ';
            }
        }

        const description = descriptionParts.join(' ');
        const restrictedRoleIds = extractRoleIds(restrictedRolesString.trim());

        const simulatedInteraction = {
            channel: message.channel,
            guild: message.guild,
            user: message.author,
            deferred: false,
            replied: false,
            async reply(options) {
                if (options.flags && options.flags.includes(MessageFlags.Ephemeral)) {
                     console.warn('Attempted to send ephemeral reply from prefix command, but not supported. Sending normally.');
                     writeToLog('Attempted to send ephemeral reply from prefix command, but not supported. Sending normally.');
                }
                const msg = await message.reply(options.content || { embeds: options.embeds, components: options.components });
                this.replied = true;
                return msg;
            },
            async followUp(options) {
                const msg = await message.channel.send(options.content || { embeds: options.embeds, components: options.components });
                this.replied = true;
                return msg;
            },
            isRepliable: () => true,
        };

        await handleCreateEvent(message.channel, title, date, startTime, endTime, description, restrictedRoleIds, simulatedInteraction, message.guild, threadOpenHoursBefore);
    }
});


// --- Client Ready Event ---
client.once('ready', async () => {
    console.log(`Logged in as ${client.user.tag}!`);
    writeToLog(`Bot logged in as ${client.user.tag}!`);
    writeToLog(`Configured SL_CERTIFIED_ROLE_ID: ${SL_CERTIFIED_ROLE_ID}`);
    writeToLog(`Configured TC_CERTIFIED_ROLE_ID: ${TC_CERTIFIED_ROLE_ID}`);
    writeToLog(`Configured CMDR_CERTIFIED_ROLE_ID: ${CMDR_CERTIFIED_ROLE_ID}`);
    writeToLog(`Configured RECON_CERTIFIED_ROLE_ID: ${RECON_CERTIFIED_ROLE_ID}`);
    writeToLog(`Configured DELETE_EVENT_ROLE_ID: ${DELETE_EVENT_ROLE_ID}`);


    // --- PostgreSQL Initialization ---
    try {
        pgPool = new Pool({
            user: process.env.PGUSER,
            host: process.env.PGHOST,
            database: process.env.PGDATABASE,
            password: process.env.PGPASSWORD,
            port: process.env.PGPORT,
            // You might want to add connectionString for easier configuration in some environments
            // connectionString: process.env.DATABASE_URL, 
            ssl: {
                rejectUnauthorized: false // Use this if connecting to a remote DB with self-signed certs (e.g., ElephantSQL free tier)
            }
        });

        // Test the connection
        await pgPool.query('SELECT NOW()');
        console.log('PostgreSQL connected successfully!');
        writeToLog('PostgreSQL connected successfully!');

        // Create events table if it doesn't exist
        // Note: IF NOT EXISTS only creates a table if it doesn't exist.
        // It does NOT update existing tables with new columns.
        await pgPool.query(`
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                description TEXT NOT NULL,
                restricted_roles JSONB,
                attendees JSONB,
                roles JSONB,
                thread_open_hours_before INTEGER,
                channel_id TEXT NOT NULL,
                message_id TEXT,
                thread_id TEXT,
                thread_opened_at TEXT,
                thread_roster_message_id TEXT,
                creator_id TEXT NOT NULL
            );
        `);
        console.log('Ensured "events" table exists in PostgreSQL.');
        writeToLog('Ensured "events" table exists in PostgreSQL.');

        // Add new columns if they don't exist (schema migration)
        await pgPool.query(`
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='thread_id') THEN
                    ALTER TABLE events ADD COLUMN thread_id TEXT;
                    ALTER TABLE events ADD COLUMN thread_opened_at TEXT;
                    ALTER TABLE events ADD COLUMN thread_roster_message_id TEXT;
                END IF;
            END
            $$;
        `);
        console.log('Ensured new thread-related columns exist in "events" table.');
        writeToLog('Ensured new thread-related columns exist in "events" table.');


        // Load existing events from PostgreSQL into in-memory cache
        const res = await pgPool.query(`SELECT * FROM events`);
        res.rows.forEach(dbEvent => {
            writeToLog(`[Client Ready] Loading event ${dbEvent.id} from DB. thread_open_hours_before: ${dbEvent.thread_open_hours_before}`);

            events[dbEvent.id] = {
                ...dbEvent,
                restrictedRoles: dbEvent.restricted_roles, // Map snake_case to camelCase
                threadOpenHoursBefore: dbEvent.thread_open_hours_before,
                channelId: dbEvent.channel_id,
                messageId: dbEvent.message_id,
                threadId: dbEvent.thread_id,
                threadOpenedAt: dbEvent.thread_opened_at,
                threadRosterMessageId: dbEvent.thread_roster_message_id,
                creatorId: dbEvent.creator_id,
                attendees: dbEvent.attendees, // JSONB comes out as JS object
                roles: dbEvent.roles // JSONB comes out as JS object
            };
            writeToLog(`Loaded event ${dbEvent.id} from PostgreSQL into in-memory cache. Attendees: ${JSON.stringify(events[dbEvent.id].attendees)}`);

            // Re-schedule threads for events that were in progress before bot restart
            if (events[dbEvent.id].threadOpenHoursBefore > 0) {
                // Parse event date and time as UTC
                const eventDateTime = moment.utc(`${events[dbEvent.id].date} ${events[dbEvent.id].startTime}`, 'DD-MM-YYYY HH:mm');
                const openTime = moment.utc(eventDateTime).subtract(events[dbEvent.id].threadOpenHoursBefore, 'hours');
                const now = moment.utc(); // Get current UTC time

                if (openTime.isAfter(now)) { // If thread opening is still in the future
                    writeToLog(`Re-scheduling thread opening for future event ${dbEvent.id}.`);
                    // Ensure guild is available before scheduling. client.guilds.cache might not be fully populated immediately.
                    const guild = client.guilds.cache.get(process.env.GUILD_ID);
                    if (guild) scheduleThreadOpening(dbEvent.id, events[dbEvent.id], guild);
                    else writeToLog(`Guild not available for re-scheduling thread opening for event ${dbEvent.id}.`);
                } else if (!events[dbEvent.id].threadId && openTime.isBefore(now)) {
                    // If open time passed and thread not yet created (e.g., bot was down during thread opening time)
                    writeToLog(`Attempting to open thread immediately for event ${dbEvent.id} (open time passed and thread not active).`);
                    const guild = client.guilds.cache.get(process.env.GUILD_ID);
                    if (guild) scheduleThreadOpening(dbEvent.id, events[dbEvent.id], guild);
                    else writeToLog(`Guild not available for immediate thread opening for event ${dbEvent.id}.`);
                }
            }
             // Re-schedule thread deletion for events whose threads are open and not yet deleted
            if (events[dbEvent.id].threadId && events[dbEvent.id].threadOpenedAt) {
                 // Parse event end date and time as UTC
                 const eventEndDateTime = moment.utc(`${events[dbEvent.id].date} ${events[dbEvent.id].endTime}`, 'DD-MM-YYYY HH:mm');
                 // Calculate deletion time based on UTC
                 const deleteTime = moment.utc(eventEndDateTime).add(1, 'day').startOf('day').add(1, 'minute');
                 const now = moment.utc(); // Get current UTC time
                 if (deleteTime.isAfter(now)) {
                    writeToLog(`Re-scheduling thread deletion for event ${dbEvent.id}.`);
                    const guild = client.guilds.cache.get(process.env.GUILD_ID);
                    if (guild) scheduleThreadDeletion(dbEvent.id, events[dbEvent.id], events[dbEvent.id].threadId, guild);
                    else writeToLog(`Guild not available for re-scheduling thread deletion for event ${dbEvent.id}.`);
                 }
            }
        });

    } catch (dbInitError) {
        console.error('Failed to initialize PostgreSQL:', dbInitError);
        writeToLog(`Failed to initialize PostgreSQL: ${dbInitError.message}`);
        // Exit process or handle gracefully if DB is critical for bot function
        process.exit(1);
    }

    await registerSlashCommands();
    
    cleanupOldLogs();
    setInterval(cleanupOldLogs, 24 * 60 * 60 * 1000);
});

// Log in to Discord with your bot token
client.login(process.env.DISCORD_TOKEN);
