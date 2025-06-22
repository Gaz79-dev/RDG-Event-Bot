const { Client, GatewayIntentBits, EmbedBuilder, REST, Routes, ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType, StringSelectMenuBuilder, StringSelectMenuOptionBuilder, MessageFlags } = require('discord.js');
const dotenv = require('dotenv');
const moment = require('moment'); // For date/time handling
const fs = require('fs');     // For file system operations (logging)
const path = require('path'); // For path manipulation (logging)

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
const SL_CERTIFIED_ROLE_ID = '1386355748111388722';
// IMPORTANT: This is the actual ID of your "@TC certified" Discord role.
// This ID is used to conditionally display the "Tank Commander" class.
const TC_CERTIFIED_ROLE_ID = '1386355942550933574';
// IMPORTANT: This is the actual ID of your "Cmdr certified" Discord role.
// This ID is used to conditionally display the "Commander" primary role.
const CMDR_CERTIFIED_ROLE_ID = '1386413663501680973';
// IMPORTANT: This is the actual ID of your "Recon certified" Discord role.
// This ID is used to conditionally display the "Recon" primary role.
const RECON_CERTIFIED_ROLE_ID = '1386413539157086248';


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


// --- In-Memory Data Storage (NOTE: Not persistent across bot restarts) ---
let events = {};

// --- Helper Functions ---

const extractRoleIds = (roleString) => {
    if (!roleString) return [];
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
    const event = events[eventId];
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
        writeToLog(`[updateThreadRosterMessage] Event ${eventId} - Accepted Attendees before role filter: ${JSON.stringify(acceptedAttendees.map(a => `${a.userId}:${a.primaryRole}`))}`);

        for (const roleName of rolesForDisplay) {
            const membersInRole = acceptedAttendees
                .filter(a => a.primaryRole === roleName)
                .map(attendee => { // Directly use 'attendee' as the iterated object
                    // Use the emoji stored directly on the attendee object (which will be class emoji or role emoji)
                    return attendee.emoji
                        ? `<@${attendee.userId}> ${attendee.emoji}`
                        : `<@${attendee.userId}>`; // Fallback if no emoji set for some reason
                });

            const fieldValue = membersInRole.length > 0 ? membersInRole.join('\n') : 'No one';
            rosterEmbed.addFields({ name: `${roleName} ${event.roles.find(r => r.primaryRole === roleName).emoji}`, value: fieldValue, inline: true });
        }

        if (rolesForDisplay.length % 3 === 1) {
            rosterEmbed.addFields({ name: '\u200B', value: '\u200B', inline: true });
            rosterEmbed.addFields({ name: '\u200B', value: '\u200B', inline: true });
        } else if (rolesForDisplay.length % 3 === 2) {
            rosterEmbed.addFields({ name: '\u200B', value: '\u200B', inline: true });
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
    const event = events[eventId];
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
            // Corrected: Use the threadOpenHoursBefore parameter directly, not from event object yet
            const openTimeMoment = moment(`${event.date} ${event.startTime}`, 'DD-MM-YYYY HH:mm').subtract(event.threadOpenHoursBefore, 'hours');
            updatedEmbed.addFields({ name: 'Discussion Thread Opens', value: `**${openTimeMoment.format('DD-MM-YYYY HH:mm')}** (${openTimeMoment.fromNow()})`, inline: false });
        } else {
            updatedEmbed.addFields({ name: 'Discussion Thread', value: `Will open at event start time.`, inline: false });
        }

        const acceptedAttendees = event.attendees.filter(a => a.rsvpStatus === 'Attending');
        const rolesForDisplay = ['Commander', 'Infantry', 'Armour', 'Recon'];
        writeToLog(`[updateEventRosterEmbed] Event ${eventId} - Accepted Attendees before role filter: ${JSON.stringify(acceptedAttendees.map(a => `${a.userId}:${a.primaryRole}`))}`);


        for (const roleName of rolesForDisplay) {
            const membersInRole = acceptedAttendees
                .filter(a => a.primaryRole === roleName)
                .map(attendee => { // Directly use 'attendee' as the iterated object
                    // Use the emoji stored directly on the attendee object (which will be class emoji or role emoji)
                    return attendee.emoji
                        ? `<@${attendee.userId}> ${attendee.emoji}`
                        : `<@${attendee.userId}>`; // Fallback if no emoji set for some reason
                });


            const fieldValue = membersInRole.length > 0 ? membersInRole.join('\n') : 'No one';
            updatedEmbed.addFields({ name: `${roleName} ${event.roles.find(r => r.primaryRole === roleName).emoji}`, value: fieldValue, inline: true });
        }
        if (rolesForDisplay.length % 3 === 1) {
            updatedEmbed.addFields({ name: '\u200B', value: '\u200B', inline: true });
            updatedEmbed.addFields({ name: '\u200B', value: '\u200B', inline: true });
        } else if (rolesForDisplay.length % 3 === 2) {
             updatedEmbed.addFields({ name: '\u200B', value: '\u200B', inline: true });
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
    const eventDateTime = moment(`${eventDetails.date} ${eventDetails.startTime}`, 'DD-MM-YYYY HH:mm');
    const openTime = moment(eventDateTime).subtract(eventDetails.threadOpenHoursBefore, 'hours');
    const now = moment();

    const delay = Math.max(0, openTime.diff(now));

    writeToLog(`Scheduling thread opening for event ${eventId} in ${delay / 1000} seconds (at ${openTime.format('YYYY-MM-DD HH:mm:ss')})`);

    setTimeout(async () => {
        try {
            const channel = guild.channels.cache.get(eventDetails.channelId);
            if (!channel) {
                writeToLog(`Failed to open thread for event ${eventId}: Channel ${eventDetails.channelId} not found.`);
                return;
            }

            const eventMessage = await channel.messages.fetch(eventDetails.messageId);
            
            writeToLog(`[scheduleThreadOpening] Attempting to start thread for event ${eventId} from message ${eventDetails.messageId}.`);
            const thread = await eventMessage.startThread({
                name: `${eventDetails.title} Discussion`,
                autoArchiveDuration: 60,
                type: ChannelType.PublicThread,
            });
            writeToLog(`[scheduleThreadOpening] Successfully started thread for event ${eventId}. New thread ID: ${thread.id}`);


            events[eventId].threadId = thread.id;
            events[eventId].threadOpenedAt = moment().toISOString();
            writeToLog(`Thread "${eventDetails.title} Discussion" opened for event ${eventId} (Thread ID: ${thread.id})`);

            const initialThreadRosterMessage = await thread.send({ embeds: [new EmbedBuilder().setTitle('Loading Roster...')], content: 'Roster will appear here once updated.' });
            events[eventId].threadRosterMessageId = initialThreadRosterMessage.id;
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
    const eventEndDateTime = moment(`${eventDetails.date} ${eventDetails.endTime}`, 'DD-MM-YYYY HH:mm');
    const deleteTime = moment(eventEndDateTime).add(1, 'day').startOf('day').add(1, 'minute');
    const now = moment();

    const delay = Math.max(0, deleteTime.diff(now));

    writeToLog(`Scheduling thread deletion for event ${eventId} in ${delay / 1000} seconds (at ${deleteTime.format('YYYY-MM-DD HH:mm:ss')})`);

    setTimeout(async () => {
        try {
            const thread = guild.channels.cache.get(threadId);
            if (thread && thread.isThread()) {
                await thread.delete();
                events[eventId].threadId = null;
                events[eventId].threadOpenedAt = null;
                events[eventId].threadRosterMessageId = null;
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
        if (!interaction.deferred && !interaction.replied) {
            await interaction.reply({ content: 'Could not determine the channel to send the event message. Please ensure the bot has "View Channel" and "Send Messages" permissions in this channel.', flags: [MessageFlags.Ephemeral] });
        } else {
            await interaction.followUp({ content: 'Could not determine the channel to send the event message. Please ensure the bot has "View Channel" and "Send Messages" permissions in this channel.', flags: [MessageFlags.Ephemeral] });
        }
        writeToLog(`Failed to create event "${title}" - Channel object was null or undefined.`);
        return;
    }

    const eventId = `${title}-${moment(`${date} ${startTime}`, 'DD-MM-YYYY HH:mm').format('DD-MM-YYYY HH:mm')}`;
    
    if (events[eventId]) {
        await interaction.followUp({ content: 'An event with this title, date, and start time already exists!', flags: [MessageFlags.Ephemeral] });
        writeToLog(`Attempted to create duplicate event: "${title}" at ${date} ${startTime}`);
        return;
    }

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

    events[eventId] = {
        title,
        date,
        startTime,
        endTime,
        description, // Ensure description is passed here
        restrictedRoles: restrictedRoleIds,
        attendees: [],
        roles: defaultPrimaryRoles, // Assign the detailed roles structure
        threadOpenHoursBefore: threadOpenHoursBefore, // Use the parameter directly
        channelId: channel.id,
        messageId: null,
        threadId: null,
        threadOpenedAt: null,
        threadRosterMessageId: null,
    };

    const embed = new EmbedBuilder()
        .setTitle(`Event: ${title}`)
        .setDescription(description)
        .addFields(
            { name: 'Date', value: moment(date, 'DD-MM-YYYY').format('DD-MM-YYYY') },
            { name: 'Time', value: `${startTime} - ${endTime} (24h format)` }
        );

    if (restrictedRoleIds && restrictedRoleIds.length > 0) {
        const roleMentions = restrictedRoleIds.map(id => `<@&${id}>`).join(', ');
        embed.addFields({ name: 'Restricted To Roles', value: roleMentions, inline: false });
    }

    if (threadOpenHoursBefore > 0) {
        // Corrected: Use the threadOpenHoursBefore parameter directly, not from event object yet
        const openTimeMoment = moment(`${date} ${startTime}`, 'DD-MM-YYYY HH:mm').subtract(threadOpenHoursBefore, 'hours');
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
        );

    try {
        writeToLog(`[handleCreateEvent] Attempting to editReply with main event message for event: ${title}`);
        const eventMessage = await interaction.editReply({
            embeds: [embed],
            components: [row]
        });
        writeToLog(`[handleCreateEvent] Successfully edited reply for event: ${title}. Message ID: ${eventMessage.id}`);


        events[eventId].messageId = eventMessage.id;
        writeToLog(`Main event message sent for event "${title}" (ID: ${eventId}).`);

        await updateEventRosterEmbed(eventId, guild);
        writeToLog(`Scheduling thread opening for event ${eventId}.`);
        scheduleThreadOpening(eventId, events[eventId], guild);
        writeToLog(`Event "${title}" fully set up (scheduling complete).`);

    } catch (sendError) {
        console.error(`Failed to send main event message (editReply) for event "${title}":`, sendError);
        writeToLog(`Failed to send main event message (editReply) for event "${title}": ${sendError.message}`);
        try {
            if (!interaction.replied) {
                await interaction.followUp({ content: `An error occurred while posting the main event message. Please check bot permissions. Error: ${sendError.message}`, flags: [MessageFlags.Ephemeral] });
            } else if (interaction.deferred) {
                 await interaction.followUp({ content: `An error occurred while finalizing the event message. Please check bot permissions. Error: ${sendError.message}`, flags: [MessageFlags.Ephemeral] });
            }
        } catch (fallbackError) {
            console.error(`Failed to send fallback error message after editReply failed: ${fallbackError.message}`);
            writeToLog(`Failed to send fallback error message after editReply failed: ${fallbackError.message}`);
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
    if (!events[eventId]) {
        await interaction.followUp({ content: 'Event not found! Please use a valid Event ID.', flags: [MessageFlags.Ephemeral] });
        writeToLog(`Attempted RSVP for non-existent event: ${eventId}`);
        return;
    }

    const event = events[eventId];
    const member = await guild.members.fetch(userId);

    if (event.restrictedRoles && event.restrictedRoles.length > 0) {
        const hasRequiredRole = event.restrictedRoles.some(roleId => member.roles.cache.has(roleId));
        if (!hasRequiredRole) {
            await interaction.followUp({ content: `You do not have the required role(s) to RSVP for this event. Required roles: ${event.restrictedRoles.map(id => `<@&${id}>`).join(', ')}`, flags: [MessageFlags.Ephemeral] });
            writeToLog(`User ${userId} attempted to RSVP for event "${event.title}" but lacks required roles.`);
            return;
        }
    }

    let attendee = event.attendees.find(a => a.userId === userId);

    if (!attendee) {
        attendee = { userId, rsvpStatus: null, primaryRole: null, className: null, emoji: null }; // Initialize className and emoji
        event.attendees.push(attendee);
        writeToLog(`New attendee ${userId} added to event "${event.title}".`);
    }

    writeToLog(`[handleRSVP] Before status update - User ${userId} raw RSVP: ${rawStatusFromButton}. Attendee: ${JSON.stringify(attendee)}`);

    let newRsvpStatus;
    switch (rawStatusFromButton.toLowerCase()) {
        case 'accept':
            newRsvpStatus = 'Attending'; // Standardize to 'Attending' for accepted
            break;
        case 'tentative':
            newRsvpStatus = 'Tentative'; // Already consistent
            break;
        case 'decline':
            newRsvpStatus = 'Declined'; // Standardize to 'Declined'
            break;
        default:
            writeToLog(`[handleRSVP] Unknown RSVP status received: ${rawStatusFromButton} for user ${userId}`);
            return;
    }

    attendee.rsvpStatus = newRsvpStatus;

    if (newRsvpStatus === 'Tentative' || newRsvpStatus === 'Declined') {
        if (attendee.primaryRole !== null || attendee.className !== null) {
            writeToLog(`User ${userId} changed RSVP to ${newRsvpStatus}, clearing previous role and class: ${attendee.primaryRole} - ${attendee.className}`);
            attendee.primaryRole = null; // Clear primary role if no longer attending
            attendee.className = null;   // Clear class if no longer attending
            attendee.emoji = null;       // Clear emoji
        }
        await interaction.deleteReply().catch(error => writeToLog(`Failed to delete ephemeral reply for user ${userId}: ${error.message}`));
        writeToLog(`User ${userId} updated RSVP status to "${newRsvpStatus}" for event "${event.title}".`);

    } else if (newRsvpStatus === 'Attending') {
        // Prepare options for the primary role selection menu, applying role-based filtering
        let rolesForPrimarySelection = event.roles.map(role => {
            let addRole = true;
            if (role.primaryRole === 'Commander' && !member.roles.cache.has(CMDR_CERTIFIED_ROLE_ID)) {
                addRole = false;
            } else if (role.primaryRole === 'Recon' && !member.roles.cache.has(RECON_CERTIFIED_ROLE_ID)) {
                addRole = false;
            }
            return addRole ? new StringSelectMenuOptionBuilder()
                .setLabel(`${role.primaryRole} ${role.emoji}`)
                .setValue(role.primaryRole) : null;
        }).filter(Boolean); // Filter out nulls

        // If primary role needs to be selected
        if (!attendee.primaryRole) {
            if (rolesForPrimarySelection.length > 0) {
                const selectRoleMenu = new ActionRowBuilder()
                    .addComponents(
                        new StringSelectMenuBuilder()
                            .setCustomId(`select_role_${eventId}`)
                            .setPlaceholder('Choose your primary role...')
                            .addOptions(rolesForPrimarySelection),
                    );
                await interaction.editReply({ content: `Your RSVP for event "${event.title}" is **Accepted**! Now, please select your primary role:`, components: [selectRoleMenu], flags: [MessageFlags.Ephemeral] });
                writeToLog(`User ${userId} accepted event "${event.title}" and prompted for primary role selection.`);
            } else {
                // Should not happen if there's at least one non-restricted role, but good for edge cases
                await interaction.deleteReply().catch(error => writeToLog(`Failed to delete ephemeral reply for user ${userId}: ${error.message}`));
                await interaction.followUp({ content: `You accepted for event "${event.title}", but no primary roles are available for you to select.`, flags: [MessageFlags.Ephemeral] });
                writeToLog(`User ${userId} accepted but no primary roles were available.`);
            }
        }
        // Then handle class selection if a class-based primary role (like Infantry or Armour) is selected and no class is chosen yet
        else if ((attendee.primaryRole === 'Infantry' || attendee.primaryRole === 'Armour') && !attendee.className) {
            const primaryRoleObj = event.roles.find(r => r.primaryRole === attendee.primaryRole);
            let classesForSelection = primaryRoleObj ? primaryRoleObj.classes : [];

            // Apply conditional filtering based on primary role
            if (attendee.primaryRole === 'Infantry') {
                const isSLCertified = member.roles.cache.has(SL_CERTIFIED_ROLE_ID);
                if (!isSLCertified) {
                    classesForSelection = classesForSelection.filter(c => c.className !== 'Officer');
                    writeToLog(`User ${userId} is not SL certified, "Officer" class filtered out for Infantry selection.`);
                }
            } else if (attendee.primaryRole === 'Armour') {
                const isTCCertified = member.roles.cache.has(TC_CERTIFIED_ROLE_ID);
                if (!isTCCertified) {
                    classesForSelection = classesForSelection.filter(c => c.className !== 'Tank Commander');
                    writeToLog(`User ${userId} is not TC certified, "Tank Commander" class filtered out for Armour selection.`);
                }
            }

            if (classesForSelection.length > 0) {
                const selectClassMenu = new ActionRowBuilder()
                    .addComponents(
                        new StringSelectMenuBuilder()
                            .setCustomId(`select_class_${eventId}`) // Generic ID for class selection
                            .setPlaceholder(`Choose your ${attendee.primaryRole} class...`)
                            .addOptions(
                                classesForSelection.map(cls => new StringSelectMenuOptionBuilder()
                                    .setLabel(`${cls.className} ${cls.emoji}`)
                                    .setValue(cls.className)
                                )
                            ),
                    );
                await interaction.editReply({ content: `You have selected **${attendee.primaryRole}**. Now, please select your specific class:`, components: [selectClassMenu], flags: [MessageFlags.Ephemeral] });
                writeToLog(`User ${userId} selected ${attendee.primaryRole} and prompted for class selection.`);
            } else {
                // If no classes are available after filtering (e.g., if TC was the only option for Armour and user isn't certified)
                await interaction.deleteReply().catch(error => writeToLog(`Failed to delete ephemeral reply for user ${userId}: ${error.message}`));
                await interaction.followUp({ content: `You accepted **${attendee.primaryRole}** for event "${event.title}", but no classes are available for you to select.`, flags: [MessageFlags.Ephemeral] });
                writeToLog(`User ${userId} accepted ${attendee.primaryRole} but no classes were available.`);
            }
        } 
        // If already has both primary role and class, then just update roster
        else {
            await interaction.deleteReply().catch(error => writeToLog(`Failed to delete ephemeral reply for user ${userId}: ${error.message}`));
            writeToLog(`User ${userId} updated RSVP status to "Attending" for event "${event.title}". Role: ${attendee.primaryRole}, Class: ${attendee.className}.`);
        }
    }


    if (event.threadId && event.threadOpenedAt) {
        try {
            const thread = guild.channels.cache.get(event.threadId);
            if (thread && thread.isThread()) {
                if (newRsvpStatus === 'Attending') {
                    writeToLog(`[handleRSVP] Attempting to add user ${userId} to thread ${thread.id}.`);
                    await thread.members.add(userId);
                    writeToLog(`[handleRSVP] Successfully added user ${userId} to thread ${thread.id}.`);
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
            writeToLog(`Failed to update user ${userId} in thread ${event.threadId}: ${threadMemberError.message}`);
        }
    }

    writeToLog(`[handleRSVP] After status update - Event ${eventId} attendees: ${JSON.stringify(events[eventId].attendees.map(a => `${a.userId}:${a.rsvpStatus}:${a.primaryRole}:${a.className}`))}`);
    await updateEventRosterEmbed(eventId, guild);
    if (event.threadId && event.threadRosterMessageId) {
        await updateThreadRosterMessage(eventId, guild);
    }
};


// --- Slash Command Definitions ---
const commands = [
    {
        name: 'createevent',
        description: 'Creates a new event with start/end times & optional restricted roles. Threads will open before.',
        options: [
            {
                name: 'title',
                type: 3, // String
                description: 'The title of the event',
                required: true,
            },
            {
                name: 'date',
                type: 3, // String (DD-MM-YYYY)
                description: 'The date of the event (DD-MM-YYYY)',
                required: true,
            },
            {
                name: 'start_time',
                type: 3, // String (HH:MM)
                description: 'The start time of the event (HH:MM, 24h format)',
                required: true,
            },
            {
                name: 'end_time',
                type: 3, // String (HH:MM)
                description: 'The end time of the event (HH:MM, 24h format)',
                required: true,
            },
            {
                name: 'description',
                type: 3, // String
                description: 'A description of the event',
                required: true,
            },
            {
                name: 'thread_open_hours_before',
                type: 4, // Integer type for number of hours
                description: 'Hours before event start to open discussion thread (default: 0 = at start time)',
                required: false,
            },
            {
                name: 'restricted_roles',
                type: 3, // String type for role mentions
                description: 'Optional: Mention roles that can access this event (e.g., @Role1 @Role2)',
                required: false,
            },
        ],
    },
];

const registerSlashCommands = async () => {
    const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
    const CLIENT_ID = process.env.CLIENT_ID;
    const GUILD_ID = process.env.GUILD_ID;

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
    // Defer reply for ALL chat input commands immediately (ephemeral false for main command visibility)
    if (interaction.isChatInputCommand()) {
        await interaction.deferReply({ ephemeral: false });
        writeToLog(`Interaction deferred for chat input command: /${interaction.commandName}`);
    }
    // Defer reply for ALL button interactions immediately (ephemeral for button clicks)
    if (interaction.isButton()) {
        await interaction.deferReply({ flags: [MessageFlags.Ephemeral] });
        writeToLog(`Interaction deferred for button click: ${interaction.customId}`);
    }
    // Defer update for ALL string select menu interactions immediately
    // Note: deferUpdate is for component interactions where you intend to update the original message.
    // If you plan to send a new message instead, use deferReply.
    if (interaction.isStringSelectMenu()) {
        await interaction.deferUpdate(); // Acknowledges the interaction. The actual response will be a DM or clearing of components.
        writeToLog(`Interaction deferred (update) for select menu: ${interaction.customId}`);
    }

    try {
        if (interaction.isChatInputCommand()) {
            const { commandName, options, channel, guild } = interaction;

            if (commandName === 'createevent') {
                const title = options.getString('title');
                const date = options.getString('date');
                const startTime = options.getString('start_time');
                const endTime = options.getString('end_time');
                const description = options.getString('description');
                const threadOpenHoursBefore = options.getInteger('thread_open_hours_before') || 0;
                const restrictedRolesString = options.getString('restricted_roles');
                const restrictedRoleIds = extractRoleIds(restrictedRolesString);

                await handleCreateEvent(channel, title, date, startTime, endTime, description, restrictedRoleIds, interaction, guild, threadOpenHoursBefore);

            }
        } else if (interaction.isButton()) {
            const { customId, user, guild } = interaction;

            if (customId.startsWith('rsvp_')) {
                const parts = customId.split('_');
                const rawStatusFromButton = parts[1]; // 'accept', 'tentative', 'decline'
                const eventId = parts.slice(2).join('_');

                await handleRSVP(eventId, user.id, rawStatusFromButton, guild, interaction);
            }
        } else if (interaction.isStringSelectMenu()) {
            const { customId, values, user, guild } = interaction;

            const eventId = customId.split('_').slice(2).join('_'); // Extract event ID from customId
            const selectedValue = values[0]; // Get the selected value

            if (!events[eventId]) {
                await interaction.followUp({ content: 'Event not found! Could not process your selection. Please try RSVPing again or contact an admin.', flags: [MessageFlags.Ephemeral] });
                writeToLog(`Error processing select menu: Event ${eventId} not found for user ${user.id}.`);
                return;
            }

            const event = events[eventId];
            const attendeeIndex = event.attendees.findIndex(a => a.userId === user.id);
            if (attendeeIndex === -1) {
                await interaction.followUp({ content: 'Could not find your RSVP for this event. Please try RSVPing again.', flags: [MessageFlags.Ephemeral] });
                writeToLog(`Could not find attendee ${user.id} for event ${eventId} during select menu interaction.`);
                return;
            }

            const attendee = event.attendees[attendeeIndex];
            const member = await guild.members.fetch(user.id);


            // --- Handle Primary Role Selection ---
            if (customId.startsWith('select_role_')) {
                attendee.primaryRole = selectedValue;
                attendee.rsvpStatus = 'Attending'; // Confirm attending status after primary role selection

                writeToLog(`[select_role] User ${user.id} selected primary role "${selectedValue}" for event "${event.title}".`);

                // If Infantry or Armour is selected, prompt for class
                if (selectedValue === 'Infantry' || selectedValue === 'Armour') {
                    const primaryRoleObj = event.roles.find(r => r.primaryRole === selectedValue);
                    let classesForSelection = primaryRoleObj ? primaryRoleObj.classes : [];

                    // Apply conditional filtering based on primary role
                    if (selectedValue === 'Infantry') {
                        const isSLCertified = member.roles.cache.has(SL_CERTIFIED_ROLE_ID);
                        if (!isSLCertified) {
                            classesForSelection = classesForSelection.filter(c => c.className !== 'Officer');
                            writeToLog(`User ${user.id} is not SL certified, "Officer" class filtered out for Infantry selection.`);
                        }
                    } else if (selectedValue === 'Armour') {
                        const isTCCertified = member.roles.cache.has(TC_CERTIFIED_ROLE_ID);
                        if (!isTCCertified) {
                            classesForSelection = classesForSelection.filter(c => c.className !== 'Tank Commander');
                            writeToLog(`User ${user.id} is not TC certified, "Tank Commander" class filtered out for Armour selection.`);
                        }
                    }


                    if (classesForSelection.length > 0) {
                        const selectClassMenu = new ActionRowBuilder()
                            .addComponents(
                                new StringSelectMenuBuilder()
                                    .setCustomId(`select_class_${eventId}`) // Generic ID for class selection
                                    .setPlaceholder(`Choose your ${selectedValue} class...`)
                                    .addOptions(
                                        classesForSelection.map(cls => new StringSelectMenuOptionBuilder()
                                            .setLabel(`${cls.className} ${cls.emoji}`)
                                            .setValue(cls.className)
                                        )
                                    ),
                            );
                        // Edit the same ephemeral message to show class selection
                        await interaction.editReply({ content: `You have selected **${selectedValue}**. Now, please select your specific class:`, components: [selectClassMenu], flags: [MessageFlags.Ephemeral] });
                        writeToLog(`User ${user.id} prompted for ${selectedValue} class selection for event "${event.title}".`);
                    } else {
                        // Edge case: Role selected but no classes available after filtering
                        await interaction.deleteReply().catch(error => writeToLog(`Failed to delete ephemeral reply (no classes available) for user ${user.id}: ${error.message}`));
                        await interaction.followUp({ content: `You selected **${selectedValue}** for event "${event.title}", but no classes were available for you to select. Please choose another primary role or contact an admin.`, flags: [MessageFlags.Ephemeral] });
                        writeToLog(`User ${user.id} selected ${selectedValue} but no classes available.`);
                    }
                } else {
                    // Non-class-based primary role selected (e.g., Commander, Recon), finalize RSVP
                    const primaryRoleObj = event.roles.find(r => r.primaryRole === selectedValue);
                    attendee.emoji = primaryRoleObj ? primaryRoleObj.emoji : null; // Set emoji for primary role

                    // Send DM confirmation
                    try {
                        const dmChannel = await user.createDM();
                        await dmChannel.send(`For event "${event.title}", you have successfully selected **${selectedValue}** as your primary role. Your RSVP is confirmed!`);
                        writeToLog(`Sent DM to ${user.tag} confirming primary role selection for event "${event.title}".`);
                    } catch (dmError) {
                        console.error(`Failed to send DM to user ${user.tag}: ${dmError.message}`);
                        writeToLog(`Failed to send DM to user ${user.tag}: ${dmError.message}`);
                        await interaction.followUp({ content: `You have selected **${selectedValue}** for event "${event.title}". Your RSVP is confirmed! (Could not send DM confirmation)`, flags: [MessageFlags.Ephemeral] });
                    }
                    // Delete the ephemeral message after primary role selection
                    await interaction.deleteReply().catch(error => writeToLog(`Failed to delete ephemeral reply after primary role selection for user ${user.id}: ${error.message}`));
                    writeToLog(`[select_role] User ${user.id} finalized non-class-based role selection for event "${event.title}".`);
                }
            } 
            // --- Handle Class Selection ---
            else if (customId.startsWith('select_class_')) {
                attendee.className = selectedValue;
                attendee.rsvpStatus = 'Attending'; // Ensure attending status is maintained

                const primaryRoleObj = event.roles.find(r => r.primaryRole === attendee.primaryRole); // Use attendee's current primary role
                const selectedClassObj = primaryRoleObj?.classes.find(c => c.className === selectedValue);
                attendee.emoji = selectedClassObj ? selectedClassObj.emoji : null;

                writeToLog(`[select_class] User ${user.id} selected class "${selectedValue}" for ${attendee.primaryRole} role in event "${event.title}".`);

                // Send DM confirmation
                try {
                    const dmChannel = await user.createDM();
                    await dmChannel.send(`For event "${event.title}", you have successfully selected **${attendee.primaryRole} - ${attendee.className}** as your role. Your RSVP is confirmed!`);
                    writeToLog(`Sent DM to ${user.tag} confirming class selection for event "${event.title}".`);
                } catch (dmError) {
                    console.error(`Failed to send DM to user ${user.tag}: ${dmError.message}`);
                    writeToLog(`Failed to send DM to user ${user.tag}: ${dmError.message}`);
                    await interaction.followUp({ content: `You have selected **${attendee.primaryRole} - ${attendee.className}** for event "${event.title}". Your RSVP is confirmed! (Could not send DM confirmation)`, flags: [MessageFlags.Ephemeral] });
                }

                // Delete the ephemeral message after class selection
                await interaction.deleteReply().catch(error => writeToLog(`Failed to delete ephemeral reply after class selection for user ${user.id}: ${error.message}`));
                writeToLog(`[select_class] User ${user.id} finalized class selection for event "${event.title}".`);
            }

            writeToLog(`[interactionCreate - select menu] After attendee update - Event ${eventId} attendees: ${JSON.stringify(event.attendees.map(a => `${a.userId}:${a.rsvpStatus}:${a.primaryRole}:${a.className}`))}`);

            // Always update the main event roster after any successful RSVP or role/class selection
            await updateEventRosterEmbed(eventId, guild);
            if (event.threadId && event.threadRosterMessageId) {
                await updateThreadRosterMessage(eventId, guild);
            }

        }
    } catch (error) {
        console.error(`Error handling interaction:`, error);
        console.trace(error); // This will print the full stack trace
        writeToLog(`Error handling interaction: ${error.message}`);
        // Universal error handling for interactions
        if (!interaction.replied && interaction.deferred) { // If deferred but not yet replied (or edited)
            await interaction.followUp({ content: 'An unexpected error occurred while processing your request! Please try again or contact an admin.', flags: [MessageFlags.Ephemeral] }).catch(err => {
                console.error(`Failed to send followUp error message: ${err.message}`);
                writeToLog(`Failed to send followUp error message: ${err.message}`);
            });
        } else if (!interaction.replied) { // If not deferred or replied at all (e.g. initial deferral failed)
            await interaction.reply({ content: 'An unexpected error occurred!', flags: [MessageFlags.Ephemeral] }).catch(err => {
                console.error(`Failed to send initial error reply: ${err.message}`);
                writeToLog(`Failed to send initial error reply: ${err.message}`);
            });
        }
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
            return message.reply('Usage: `!createevent <title> <DD-MM-YYYY> <HH:MM_start> <HH:MM_end> <description> [optional: <hours_before_thread>] [optional: @Role1 @Role2]`');
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

        await handleCreateEvent(message.channel, title, date, startTime, endTime, description, restrictedRoleIds, { followUp: message.reply.bind(message) }, message.guild, threadOpenHoursBefore);
    }
});


// --- Client Ready Event ---
client.once('ready', async () => {
    console.log(`Logged in as ${client.user.tag}!`);
    writeToLog(`Bot logged in as ${client.user.tag}!`);

    await registerSlashCommands();
    
    cleanupOldLogs();
    setInterval(cleanupOldLogs, 24 * 60 * 60 * 1000);

    // IMPORTANT NOTE ON PERSISTENCE:
    // With current in-memory storage (`let events = {};`), scheduled tasks (thread
    // opening/deletion) will be LOST if the bot restarts.
    // For a production-grade bot, you would need:
    // 1. A database (e.g., Firestore) to store event data persistently.
    // 2. On bot startup (`client.once('ready')`), logic to load all pending events
    //    from the database and re-schedule their thread opening/deletion tasks.
    // 3. To re-render the roster embeds by calling updateEventRosterEmbed for each active event.
    //    And similarly for updateThreadRosterMessage if you reload the roster for active threads.
});

// Log in to Discord with your bot token
client.login(process.env.DISCORD_TOKEN);
