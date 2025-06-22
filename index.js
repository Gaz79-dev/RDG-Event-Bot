const { Client, GatewayIntentBits, EmbedBuilder, REST, Routes, ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType, StringSelectMenuBuilder, StringSelectMenuOptionBuilder } = require('discord.js');
const dotenv = require('dotenv');
const moment = require('moment'); // For date/time handling
const fs = require('fs');     // For file system operations (logging)
const path = require('path'); // For path manipulation (logging)

dotenv.config(); // Load environment variables from .env file

// Initialize Discord client with necessary intents
const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,           // Required for guild-related events (channels, roles, members)
        GatewayIntentBits.GuildMessages,    // Required for message-related events
        GatewayIntentBits.MessageContent,   // Privileged intent: Required to read message content for prefix commands
        GatewayIntentBits.GuildMembers      // Privileged intent: Required to access guild member data (roles, fetching members)
    ]
});

// --- Logging Configuration ---
const logDirectory = path.join(__dirname, 'logs'); // Define a directory for logs

// Ensure log directory exists, create if not
const ensureLogDirectory = () => {
    if (!fs.existsSync(logDirectory)) {
        fs.mkdirSync(logDirectory, { recursive: true });
    }
};

// Get the current daily log file name
const getLogFileName = () => {
    return path.join(logDirectory, `bot_log_${moment().format('YYYY-MM-DD')}.log`);
};

// Write a message to the daily log file
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

// Clean up old log files (older than 5 days)
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
            // Check if the file matches the expected log file naming convention
            if (fileNameParts.length === 3 && fileNameParts[0] === 'bot' && fileNameParts[1] === 'log' && file.endsWith('.log')) {
                const datePart = fileNameParts[2].split('.')[0]; // 'YYYY-MM-DD'
                const logDate = moment(datePart, 'YYYY-MM-DD');

                // If the log file is older than 5 days, delete it
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

// --- In-Memory Data Storage (NOTE: Not persistent across bot restarts) ---
let events = {}; // Stores event details

// --- Helper Functions ---

// Extracts Discord role IDs from a string containing role mentions (e.g., "<@&ID1> <@&ID2>")
const extractRoleIds = (roleString) => {
    if (!roleString) return [];
    const roleMentions = roleString.match(/<@&(\d+)>/g); // Regex to find role mentions
    if (!roleMentions) return [];
    return roleMentions.map(mention => mention.replace(/<@&|>/g, '')); // Extract just the ID
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

        // Re-create the base embed
        const updatedEmbed = new EmbedBuilder()
            .setTitle(`Event: ${event.title}`)
            .setDescription(event.description)
            .addFields(
                { name: 'Date', value: moment(event.date, 'YYYY-MM-DD').format('YYYY-MM-DD') },
                { name: 'Time', value: `${event.startTime} - ${event.endTime} (24h format)` }
            );

        if (event.restrictedRoles && event.restrictedRoles.length > 0) {
            const roleMentions = event.restrictedRoles.map(id => `<@&${id}>`).join(', ');
            updatedEmbed.addFields({ name: 'Restricted To Roles', value: roleMentions, inline: false });
        }

        if (event.threadOpenHoursBefore > 0) {
            const openTimeMoment = moment(`${event.date} ${event.startTime}`, 'YYYY-MM-DD HH:mm').subtract(event.threadOpenHoursBefore, 'hours');
            updatedEmbed.addFields({ name: 'Discussion Thread Opens', value: `**${openTimeMoment.format('YYYY-MM-DD HH:mm')}** (${event.threadOpenHoursBefore} hours before event start)`, inline: false });
        } else {
            updatedEmbed.addFields({ name: 'Discussion Thread', value: `Will open at event start time.`, inline: false });
        }

        // --- Add Roster Breakdown ---
        const acceptedAttendees = event.attendees.filter(a => a.rsvpStatus === 'Attending');
        const rolesForDisplay = ['Commander', 'Infantry', 'Armour', 'Recon']; // Order of roles

        // Prepare fields for each role
        for (const roleName of rolesForDisplay) {
            const membersInRole = acceptedAttendees
                .filter(a => a.primaryRole === roleName)
                .map(a => `<@${a.userId}>`); // Mention the user

            // Format for display, defaulting to 'No one' if empty
            const fieldValue = membersInRole.length > 0 ? membersInRole.join('\n') : 'No one';
            updatedEmbed.addFields({ name: `${roleName} ${event.roles.find(r => r.primaryRole === roleName).emoji}`, value: fieldValue, inline: true });
        }
        // Add an empty field to ensure even spacing if there are not 3 fields in a row
        // Discord embeds try to put 3 inline fields per row.
        if (rolesForDisplay.length % 3 === 1) { // If 1 or 4 fields, add 2 empty
            updatedEmbed.addFields({ name: '\u200B', value: '\u200B', inline: true });
            updatedEmbed.addFields({ name: '\u200B', value: '\u200B', inline: true });
        } else if (rolesForDisplay.length % 3 === 2) { // If 2 or 5 fields, add 1 empty
             updatedEmbed.addFields({ name: '\u200B', value: '\u200B', inline: true });
        }

        // Add a field for 'Tentative' and 'Declined' attendees
        const tentativeAttendees = event.attendees
            .filter(a => a.rsvpStatus === 'Tentative')
            .map(a => `<@${a.userId}>`);
        const declinedAttendees = event.attendees
            .filter(a => a.rsvpStatus === 'Declined')
            .map(a => `<@${a.userId}>`);

        updatedEmbed.addFields(
            { name: 'Tentative 🤔', value: tentativeAttendees.length > 0 ? tentativeAttendees.join('\n') : 'No one', inline: false },
            { name: 'Declined ❌', value: declinedAttendees.length > 0 ? declinedAttendees.join('\n') : 'No one', inline: false }
        );


        // Re-create the RSVP buttons
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

        // Edit the original message with the updated embed and components
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
    const eventDateTime = moment(`${eventDetails.date} ${eventDetails.startTime}`, 'YYYY-MM-DD HH:mm');
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
            
            const thread = await eventMessage.startThread({
                name: `${eventDetails.title} Discussion`,
                autoArchiveDuration: 60,
                type: ChannelType.PublicThread,
            });

            events[eventId].threadId = thread.id;
            events[eventId].threadOpenedAt = moment().toISOString();
            writeToLog(`Thread "${eventDetails.title} Discussion" opened for event ${eventId} (Thread ID: ${thread.id})`);

            for (const attendee of events[eventId].attendees) {
                if (attendee.rsvpStatus === 'Attending') {
                    try {
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
    const eventEndDateTime = moment(`${eventDetails.date} ${eventDetails.endTime}`, 'YYYY-MM-DD HH:mm');
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
 * @param {string} date - The date of the event (YYYY-MM-DD).
 * @param {string} startTime - The start time of the event (HH:MM).
 * @param {string} endTime - The end time of the event (HH:MM).
 * @param {string} description - The description of the event.
 * @param {string[]} restrictedRoleIds - Array of role IDs that can access this event.
 * @param {Function} replyMethod - The function used to reply to the command/interaction.
 * @param {object} guild - The Discord Guild object.
 * @param {number} threadOpenHoursBefore - Hours before event start to open discussion thread.
 */
const handleCreateEvent = async (channel, title, date, startTime, endTime, description, restrictedRoleIds, replyMethod, guild, threadOpenHoursBefore) => {
    if (!channel) {
        await replyMethod({ content: 'Could not determine the channel to send the event message. Please ensure the bot has "View Channel" and "Send Messages" permissions in this channel.', ephemeral: true });
        writeToLog(`Failed to create event "${title}" - Channel object was null or undefined.`);
        return;
    }

    const eventId = `${title}-${moment(`${date} ${startTime}`, 'YYYY-MM-DD HH:mm').format('YYYY-MM-DD HH:mm')}`;
    
    if (events[eventId]) {
        await replyMethod({ content: 'An event with this title, date, and start time already exists!', ephemeral: true });
        writeToLog(`Attempted to create duplicate event: "${title}" at ${date} ${startTime}`);
        return;
    }

    const defaultPrimaryRoles = [
        { primaryRole: 'Commander', emoji: '👑', classes: [] },
        { primaryRole: 'Infantry', emoji: '🛡️', classes: [] },
        { primaryRole: 'Armour', emoji: '🪖', classes: [] },
        { primaryRole: 'Recon', emoji: '🔭', classes: [] },
    ];

    events[eventId] = {
        title,
        date,
        startTime,
        endTime,
        description,
        restrictedRoles: restrictedRoleIds,
        attendees: [],
        roles: defaultPrimaryRoles,
        threadOpenHoursBefore: threadOpenHoursBefore,
        channelId: channel.id,
        messageId: null,
        threadId: null,
        threadOpenedAt: null,
    };

    const embed = new EmbedBuilder()
        .setTitle(`Event: ${title}`)
        .setDescription(description)
        .addFields(
            { name: 'Date', value: moment(date, 'YYYY-MM-DD').format('YYYY-MM-DD') },
            { name: 'Time', value: `${startTime} - ${endTime} (24h format)` }
        );

    if (restrictedRoleIds && restrictedRoleIds.length > 0) {
        const roleMentions = restrictedRoleIds.map(id => `<@&${id}>`).join(', ');
        embed.addFields({ name: 'Restricted To Roles', value: roleMentions, inline: false });
    }

    if (threadOpenHoursBefore > 0) {
        const openTimeMoment = moment(`${date} ${startTime}`, 'YYYY-MM-DD HH:mm').subtract(threadOpenHoursBefore, 'hours');
        embed.addFields({ name: 'Discussion Thread Opens', value: `**${openTimeMoment.format('YYYY-MM-DD HH:mm')}** (${threadOpenHoursBefore} hours before event start)`, inline: false });
    } else {
        embed.addFields({ name: 'Discussion Thread', value: `Will open at event start time.`, inline: false });
    }

    // Create RSVP buttons
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

    const eventMessage = await channel.send({
        embeds: [embed],
        components: [row]
    });

    events[eventId].messageId = eventMessage.id;

    // Call updateRosterEmbed immediately to show initial empty roster
    await updateEventRosterEmbed(eventId, guild);

    scheduleThreadOpening(eventId, events[eventId], guild);

    await replyMethod(`Event "${title}" created with ID: \`${eventId}\`! The discussion thread will open ${threadOpenHoursBefore} hours before the event starts. Default roles (Commander, Infantry, Armour, Recon) have been automatically added.`);
    writeToLog(`Event created: "${title}" (ID: ${eventId}) on ${date} from ${startTime} to ${endTime} with thread opening ${threadOpenHoursBefore} hours before. Default roles added.`);
};


// Note: handleCreatePrimaryRole function is removed as roles are now automatically included.
// handleAssignClassToUser is removed as role selection is now part of RSVP flow for simplicity.


/**
 * Displays the defined roles and classes for a given event.
 * This is now mainly handled by `updateEventRosterEmbed` on the main event message.
 * This helper is retained for potential future text-based display needs or debugging.
 * @param {string} eventId - The ID of the event.
 * @param {Function} replyMethod - The function used to reply to the command/interaction.
 */
const handleDisplayRolesAndClasses = async (eventId, replyMethod) => {
    if (!events[eventId]) {
        await replyMethod({ content: 'Event not found! Please use a valid Event ID.', ephemeral: true });
        writeToLog(`Attempted to display roles for non-existent event: ${eventId}`);
        return;
    }

    const event = events[eventId];
    let roleInfo = '';
    if (event.roles.length === 0) {
        roleInfo = 'No roles and classes defined for this event yet.';
    } else {
        event.roles.forEach(role => {
            roleInfo += `**${role.primaryRole}**: ${role.emoji}\n`;
            if (role.classes.length > 0) {
                role.classes.forEach(classObj => {
                    roleInfo += `  - **${classObj.className}**: ${classObj.emoji}\n`;
                });
            } else {
                roleInfo += `  (No specific classes defined for this role yet)\n`;
            }
        });
    }

    await replyMethod(`Roles and Classes for event "${event.title}":\n${roleInfo}`);
    writeToLog(`Displayed roles and classes for event: "${event.title}"`);
};

/**
 * Handles RSVP status updates for a user for a given event.
 * This function is now also responsible for triggering role selection if needed.
 * @param {Function} replyMethod - The function used to reply to the command/interaction.
 * @param {string} eventId - The ID of the event.
 * @param {string} userId - The ID of the user whose RSVP status is being updated.
 * @param {string} status - The new RSVP status (Attending, Tentative, Declined).
 * @param {object} guild - The Discord Guild object.
 */
const handleRSVP = async (replyMethod, eventId, userId, status, guild) => {
    if (!events[eventId]) {
        await replyMethod({ content: 'Event not found! Please use a valid Event ID.', ephemeral: true });
        writeToLog(`Attempted RSVP for non-existent event: ${eventId}`);
        return;
    }

    const event = events[eventId];
    const member = await guild.members.fetch(userId);

    // Role restriction check for RSVP
    if (event.restrictedRoles && event.restrictedRoles.length > 0) {
        const hasRequiredRole = event.restrictedRoles.some(roleId => member.roles.cache.has(roleId));
        if (!hasRequiredRole) {
            await replyMethod({ content: `You do not have the required role(s) to RSVP for this event. Required roles: ${event.restrictedRoles.map(id => `<@&${id}>`).join(', ')}`, ephemeral: true });
            writeToLog(`User ${userId} attempted to RSVP for event "${event.title}" but lacks required roles.`);
            return;
        }
    }

    let attendee = event.attendees.find(a => a.userId === userId);

    // If attendee doesn't exist, create a new entry for them.
    // Their initial primaryRole will be null until they select one.
    if (!attendee) {
        attendee = { userId, rsvpStatus: null, primaryRole: null };
        event.attendees.push(attendee);
        writeToLog(`New attendee ${userId} added to event "${event.title}".`);
    }

    if (status === 'Attending') {
        // Update status to Attending
        attendee.rsvpStatus = status;

        if (attendee.primaryRole === null) {
            // Prompt for role selection if they don't have one yet
            const selectMenu = new ActionRowBuilder()
                .addComponents(
                    new StringSelectMenuBuilder()
                        .setCustomId(`select_role_${eventId}`)
                        .setPlaceholder('Choose your primary role...')
                        .addOptions(
                            event.roles.map(role => new StringSelectMenuOptionBuilder()
                                .setLabel(`${role.primaryRole} ${role.emoji}`)
                                .setValue(role.primaryRole)
                            )
                        ),
                );
            
            await replyMethod({ content: `Your RSVP for event "${event.title}" is **Accepted**! Now, please select your primary role:`, components: [selectMenu], ephemeral: true });
            writeToLog(`User ${userId} accepted event "${event.title}" and prompted for role selection.`);
        } else {
            // Already has a role, just confirm status update
            await replyMethod({ content: `Your RSVP status for event "${event.title}" updated to: **${status}**`, ephemeral: true });
            writeToLog(`User ${userId} updated RSVP status to "${status}" for event "${event.title}".`);
        }

        // Add user to thread if it's open
        if (event.threadId && event.threadOpenedAt) {
            try {
                const thread = guild.channels.cache.get(event.threadId);
                if (thread && thread.isThread()) {
                    await thread.members.add(userId);
                    writeToLog(`User ${userId} added to thread ${event.threadId} after accepting RSVP.`);
                }
            } catch (addError) {
                console.error(`Failed to add user ${userId} to thread ${event.threadId} after RSVP:`, addError);
                writeToLog(`Failed to add user ${userId} to thread ${event.threadId} after RSVP: ${addError.message}`);
            }
        }
    } else { // Tentative or Declined
        // Update status
        attendee.rsvpStatus = status;
        await replyMethod({ content: `Your RSVP status for event "${event.title}" updated to: **${status}**`, ephemeral: true });
        writeToLog(`User ${userId} updated RSVP status to "${status}" for event "${event.title}".`);

        // Remove user from thread if they were attending
        if (event.threadId && event.threadOpenedAt) {
            try {
                const thread = guild.channels.cache.get(event.threadId);
                if (thread && thread.isThread()) {
                    const threadMember = await thread.members.fetch(userId).catch(() => null);
                    if (threadMember) { // Only remove if they are actually in the thread
                        await thread.members.remove(userId);
                        writeToLog(`User ${userId} removed from thread ${event.threadId} after changing RSVP from Attending.`);
                    }
                }
            } catch (removeError) {
                console.error(`Failed to remove user ${userId} from thread ${event.threadId} after RSVP change:`, removeError);
                writeToLog(`Failed to remove user ${userId} from thread ${event.threadId} after RSVP change: ${removeError.message}`);
            }
        }
    }

    // Always update the roster embed after any RSVP action
    await updateEventRosterEmbed(eventId, guild);
};

// handleShowEventRoles is removed as roster is now displayed in main event message.


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
                type: 3, // String (YYYY-MM-DD)
                description: 'The date of the event (YYYY-MM-DD)',
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
    // Removed createprimaryrole command definition
    // Removed assignclass command definition
    // Removed displayroles command definition
    // Removed rsvp command definition
    // Removed showeventroles command definition
];

// Function to register slash commands with Discord's API
const registerSlashCommands = async () => {
    const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
    const CLIENT_ID = process.env.CLIENT_ID;
    const GUILD_ID = process.env.GUILD_ID; // Guild-specific for faster updates during development

    if (!CLIENT_ID) {
        console.error('CLIENT_ID is not defined in .env! Cannot register commands.');
        writeToLog('CLIENT_ID is not defined in .env! Cannot register commands.');
        return;
    }

    try {
        console.log('Started refreshing application (/) commands.');
        writeToLog('Started refreshing application (/) commands.');

        if (GUILD_ID) {
            // Register guild-specific commands (faster updates)
            await rest.put(Routes.applicationGuildCommands(CLIENT_ID, GUILD_ID), { body: commands });
            console.log(`Successfully reloaded application (/) commands for guild ${GUILD_ID}.`);
            writeToLog(`Successfully reloaded application (/) commands for guild ${GUILD_ID}.`);
        } else {
            // Deploy global commands (takes up to an hour to propagate)
            await rest.put(Routes.applicationCommands(CLIENT_ID), { body: commands });
            console.log('Successfully reloaded application (/) commands globally.');
            writeToLog('Successfully reloaded application (/) commands globally.');
        }

    } catch (error) {
        console.error('Failed to register slash commands:', error);
        writeToLog(`Failed to register slash commands: ${error.message}`);
    }
};


// --- Event Listeners for Discord Client ---

// Handles all incoming interactions (slash commands, buttons, select menus, etc.)
client.on('interactionCreate', async (interaction) => {
    // Defer reply for slash commands to ensure sufficient time for processing
    if (interaction.isChatInputCommand()) {
        await interaction.deferReply({ ephemeral: false });
    }

    try {
        if (interaction.isChatInputCommand()) { // Handle Slash Commands
            const { commandName, options, channel, user, guild } = interaction;

            if (commandName === 'createevent') {
                const title = options.getString('title');
                const date = options.getString('date');
                const startTime = options.getString('start_time');
                const endTime = options.getString('end_time');
                const description = options.getString('description');
                const threadOpenHoursBefore = options.getInteger('thread_open_hours_before') || 0;
                const restrictedRolesString = options.getString('restricted_roles');
                const restrictedRoleIds = extractRoleIds(restrictedRolesString);

                await handleCreateEvent(channel, title, date, startTime, endTime, description, restrictedRoleIds, interaction.followUp.bind(interaction), guild, threadOpenHoursBefore);

            }
        } else if (interaction.isButton()) { // Handle Button Interactions (like RSVP buttons)
            const { customId, user, guild } = interaction;
            await interaction.deferReply({ ephemeral: true });

            if (customId.startsWith('rsvp_')) {
                const parts = customId.split('_');
                const status = parts[1].charAt(0).toUpperCase() + parts[1].slice(1);
                const eventId = parts.slice(2).join('_');

                await handleRSVP(interaction.followUp.bind(interaction), eventId, user.id, status, guild);
            }
        } else if (interaction.isStringSelectMenu()) { // Handle Select Menu Interactions
            const { customId, values, user, guild } = interaction;
            await interaction.deferUpdate(); // Acknowledge the select menu interaction immediately

            if (customId.startsWith('select_role_')) {
                const eventId = customId.replace('select_role_', '');
                const selectedRole = values[0]; // Get the selected value from the menu

                if (!events[eventId]) {
                    await interaction.followUp({ content: 'Event not found! Could not assign role.', ephemeral: true });
                    writeToLog(`Error assigning role: Event ${eventId} not found for select menu interaction.`);
                    return;
                }

                const attendeeIndex = events[eventId].attendees.findIndex(a => a.userId === user.id);
                if (attendeeIndex !== -1) {
                    events[eventId].attendees[attendeeIndex].primaryRole = selectedRole;
                    // Ensure RSVP status is "Attending" if role is selected, in case it was pending
                    events[eventId].attendees[attendeeIndex].rsvpStatus = 'Attending';
                    await interaction.followUp({ content: `You have selected **${selectedRole}** for event "${events[eventId].title}".`, ephemeral: true });
                    writeToLog(`User ${user.id} selected role "${selectedRole}" for event "${events[eventId].title}".`);

                    // Update the event roster embed after role selection
                    await updateEventRosterEmbed(eventId, guild);
                } else {
                    await interaction.followUp({ content: 'Could not find your RSVP for this event to assign a role. Please try RSVPing again.', ephemeral: true });
                    writeToLog(`Could not find attendee ${user.id} for event ${eventId} during role selection.`);
                }
            }
        }
    } catch (error) {
        console.error(`Error handling interaction:`, error);
        writeToLog(`Error handling interaction: ${error.message}`);
        if (!interaction.deferred && !interaction.replied) {
            await interaction.reply({ content: 'There was an error while executing this command/interaction!', ephemeral: true });
        } else {
            await interaction.followUp({ content: 'There was an error while executing this command/interaction!', ephemeral: true });
        }
    }
});


// Handles traditional prefix commands (e.g., "!createevent")
client.on('messageCreate', async (message) => {
    if (message.author.bot) return;

    const args = message.content.split(' ');
    const command = args[0].toLowerCase();
    const replyMethod = message.reply.bind(message);

    // !createevent <title> <YYYY-MM-DD> <HH:MM_start> <HH:MM_end> <description> [optional: <hours_before_thread>] [optional: @Role1 @Role2]
    if (command === '!createevent') {
        if (args.length < 6) {
            writeToLog(`Invalid !createevent command from ${message.author.id}: ${message.content}`);
            return message.reply('Usage: `!createevent <title> <YYYY-MM-DD> <HH:MM_start> <HH:MM_end> <description> [optional: <hours_before_thread>] [optional: @Role1 @Role2]`');
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
                    restrictedRolesString += arg + ' '; // Fallback: if not role, assume part of roles string (simplistic)
                }
            } else if (parsingState === 'roles') {
                restrictedRolesString += arg + ' ';
            }
        }

        const description = descriptionParts.join(' ');
        const restrictedRoleIds = extractRoleIds(restrictedRolesString.trim());

        await handleCreateEvent(message.channel, title, date, startTime, endTime, description, restrictedRoleIds, replyMethod, message.guild, threadOpenHoursBefore);
    }

    // Removed handling for assignclass, displayroles, rsvp, showeventroles prefix commands
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
});

// Log in to Discord with your bot token
client.login(process.env.DISCORD_TOKEN);
