const { Client, GatewayIntentBits, EmbedBuilder } = require('discord.js');
const dotenv = require('dotenv');
const moment = require('moment');
const fs = require('fs');     // Import the file system module
const path = require('path'); // Import the path module

dotenv.config();

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildMembers
    ]
});

// Define a directory for logs relative to the application's working directory
const logDirectory = path.join(__dirname, 'logs');

// Function to ensure log directory exists
const ensureLogDirectory = () => {
    if (!fs.existsSync(logDirectory)) {
        fs.mkdirSync(logDirectory, { recursive: true }); // recursive: true creates parent directories if they don't exist
    }
};

// Function to get the current daily log file name
const getLogFileName = () => {
    return path.join(logDirectory, `bot_log_${moment().format('YYYY-MM-DD')}.log`);
};

// Function to write to the daily log file
const writeToLog = (message) => {
    ensureLogDirectory(); // Ensure the log directory exists before writing
    const logFileName = getLogFileName();
    const timestamp = moment().format('YYYY-MM-DD HH:mm:ss');
    try {
        fs.appendFileSync(logFileName, `[${timestamp}] ${message}\n`);
    } catch (error) {
        console.error(`Failed to write to log file ${logFileName}:`, error);
    }
};

// Function to clean up old log files (older than 5 days)
const cleanupOldLogs = () => {
    ensureLogDirectory(); // Ensure the log directory exists before listing
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

                // Check if the log file is older than 5 days
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


// Store events in memory
let events = {};

// Store roles and classes with emojis in memory for each event
let eventRoles = {};

// Helper function to create events with roles
const createEvent = (channel, title, dateTime, description, imageUrl) => {
    const eventId = `${title}-${moment(dateTime).format('YYYY-MM-DD HH:mm')}`;
    events[eventId] = {
        title,
        dateTime,
        description,
        imageUrl,
        attendees: [],
        roles: [],  // Primary roles and classes with emojis will be stored here
    };

    // Send a message in the channel
    const embed = new EmbedBuilder()
        .setTitle(`Event: ${title}`)
        .setDescription(description)
        .setImage(imageUrl)
        .addFields(
            { name: 'Date & Time', value: moment(dateTime).format('YYYY-MM-DD HH:mm') }
        );
    channel.send({ embeds: [embed] });
    writeToLog(`Event created: "${title}" at ${dateTime}`);
};

// Command to create a primary role with classes and emojis
const createPrimaryRole = (message, eventId, primaryRole, primaryRoleEmoji, classesWithEmojis) => {
    if (!events[eventId]) {
        writeToLog(`Attempted to create primary role for non-existent event: ${eventId}`);
        return message.reply('Event not found!');
    }

    // Ensure the role doesn't already exist
    if (events[eventId].roles.some(role => role.primaryRole === primaryRole)) {
        writeToLog(`Attempted to create duplicate primary role "${primaryRole}" for event "${events[eventId].title}"`);
        return message.reply('This primary role already exists!');
    }

    // Parse classes with emojis
    const classes = classesWithEmojis.map(classWithEmoji => {
        const [emoji, ...classParts] = classWithEmoji.split(' ');
        const className = classParts.join(' ');
        return { className, emoji };
    });

    // Add the primary role with its classes and emojis to the event
    events[eventId].roles.push({ primaryRole, emoji: primaryRoleEmoji, classes });

    message.reply(`Primary Role "${primaryRole}" with emoji "${primaryRoleEmoji}" and classes [${classes.map(c => `${c.emoji} ${c.className}`).join(', ')}] created for event "${events[eventId].title}"`);
    writeToLog(`Primary Role "${primaryRole}" created for event "${events[eventId].title}"`);
};

// Command to assign a class with emoji to a user for a given event
const assignClassToUser = (message, eventId, userId, primaryRole, className) => {
    if (!events[eventId]) {
        writeToLog(`Attempted to assign class for non-existent event: ${eventId}`);
        return message.reply('Event not found!');
    }

    // Check if the primary role exists
    const role = events[eventId].roles.find(role => role.primaryRole === primaryRole);
    if (!role) {
        writeToLog(`Primary role "${primaryRole}" not found for event "${events[eventId].title}" when assigning class to user ${userId}`);
        return message.reply(`Primary role "${primaryRole}" not found in event "${events[eventId].title}"`);
    }

    // Check if the class exists under the primary role
    const classObj = role.classes.find(c => c.className === className);
    if (!classObj) {
        writeToLog(`Class "${className}" not found under role "${primaryRole}" for event "${events[eventId].title}" when assigning class to user ${userId}`);
        return message.reply(`Class "${className}" not found under role "${primaryRole}"`);
    }

    // Add the user to the event with the specified role and class
    const attendee = events[eventId].attendees.find(a => a.userId === userId);
    if (!attendee) {
        events[eventId].attendees.push({ userId, primaryRole, className, emoji: classObj.emoji, rsvpStatus: 'Tentative' });
        writeToLog(`User ${userId} assigned to "${primaryRole} - ${className}" in event "${events[eventId].title}"`);
    } else {
        writeToLog(`User ${userId} re-assigned from "${attendee.primaryRole} - ${attendee.className}" to "${primaryRole} - ${className}" in event "${events[eventId].title}"`);
        attendee.primaryRole = primaryRole;
        attendee.className = className;
        attendee.emoji = classObj.emoji;
    }

    message.reply(`User <@${userId}> assigned to "${primaryRole} - ${className}" with emoji "${classObj.emoji}" in event "${events[eventId].title}"`);
};

// Command to display the roles and classes with emojis for an event
const displayRolesAndClasses = (message, eventId) => {
    if (!events[eventId]) {
        writeToLog(`Attempted to display roles for non-existent event: ${eventId}`);
        return message.reply('Event not found!');
    }

    const event = events[eventId];
    let roleInfo = '';
    event.roles.forEach(role => {
        roleInfo += `**${role.primaryRole}**: ${role.emoji}\n`;
        role.classes.forEach(classObj => {
            roleInfo += `  - **${classObj.className}**: ${classObj.emoji}\n`;
        });
    });

    message.reply(`Roles and Classes for event "${event.title}":\n${roleInfo}`);
    writeToLog(`Displayed roles and classes for event: "${event.title}"`);
};

// Command to handle RSVP (attending with primary roles and classes)
const handleRSVP = (message, eventId, userId, status) => {
    if (!events[eventId]) {
        writeToLog(`Attempted RSVP for non-existent event: ${eventId}`);
        return message.reply('Event not found!');
    }

    const event = events[eventId];
    const attendee = event.attendees.find(a => a.userId === userId);
    if (!attendee) {
        writeToLog(`User ${userId} attempted to RSVP for event "${event.title}" but is not signed up.`);
        return message.reply('You are not signed up for this event!');
    }

    // Update RSVP status
    attendee.rsvpStatus = status;
    message.reply(`RSVP status for <@${userId}> updated to: ${status}`);
    writeToLog(`User ${userId} updated RSVP status to "${status}" for event "${event.title}"`);
};

// Command to show the breakdown of users with roles and emojis
const showEventRoles = (message, eventId) => {
    if (!events[eventId]) {
        writeToLog(`Attempted to show event roles for non-existent event: ${eventId}`);
        return message.reply('Event not found!');
    }

    const event = events[eventId];
    let attendeeInfo = '';
    event.roles.forEach(role => {
        attendeeInfo += `**${role.primaryRole}** (${role.emoji}): \n`;
        role.classes.forEach(classObj => {
            const classAttendees = event.attendees.filter(a => a.primaryRole === role.primaryRole && a.className === classObj.className);
            attendeeInfo += `  - **${classObj.className}** (${classObj.emoji}): ${classAttendees.map(a => `<@${a.userId}>`).join(', ') || 'No one'}\n`;
        });
    });

    message.reply(`Event role breakdown:\n${attendeeInfo}`);
    writeToLog(`Displayed event role breakdown for event: "${event.title}"`);
};

// Event creation command
client.on('messageCreate', async (message) => {
    if (message.author.bot) return;

    const args = message.content.split(' ');

    // !createevent <title> <YYYY-MM-DD> <HH:MM> <description> <image_url>
    if (args[0].toLowerCase() === '!createevent') {
        if (args.length < 6) {
            writeToLog(`Invalid !createevent command from ${message.author.id}: ${message.content}`);
            return message.reply('Usage: !createevent <title> <YYYY-MM-DD> <HH:MM> <description> <image_url>');
        }

        const [title, date, time, ...descriptionParts] = args.slice(1);
        // Correctly extract description and image_url, assuming image_url is always the last arg
        const imageUrl = descriptionParts[descriptionParts.length - 1];
        const description = descriptionParts.slice(0, -1).join(' ');
        const dateTime = `${date} ${time}`;

        createEvent(message.channel, title, dateTime, description, imageUrl);
        message.reply(`Event "${title}" created!`);
    }

    // !createprimaryrole <event_id> <primary_role> <emoji> <class1_emoji class1, class2_emoji class2,...>
    if (args[0].toLowerCase() === '!createprimaryrole') {
        if (args.length < 4) {
            writeToLog(`Invalid !createprimaryrole command from ${message.author.id}: ${message.content}`);
            return message.reply('Usage: !createprimaryrole <event_id> <primary_role> <emoji> <class1_emoji class1,class2_emoji class2,...>');
        }

        const eventId = args[1];
        const primaryRole = args[2];
        const primaryRoleEmoji = args[3];
        // Ensure classesWithEmojis are correctly parsed, handling multi-word class names
        const classesWithEmojis = args.slice(4).join(' ').split(',').map(s => s.trim());

        createPrimaryRole(message, eventId, primaryRole, primaryRoleEmoji, classesWithEmojis);
    }

    // !assignclass <event_id> <user_id> <primary_role> <class_name>
    if (args[0].toLowerCase() === '!assignclass') {
        if (args.length < 5) {
            writeToLog(`Invalid !assignclass command from ${message.author.id}: ${message.content}`);
            return message.reply('Usage: !assignclass <event_id> <user_id> <primary_role> <class_name>');
        }

        const eventId = args[1];
        const userId = args[2].replace(/[<@!>]/g, '');  // Remove @ and <> symbols
        const primaryRole = args[3];
        const className = args.slice(4).join(' '); // Class name can be multiple words

        assignClassToUser(message, eventId, userId, primaryRole, className);
    }

    // !displayroles <event_id>
    if (args[0].toLowerCase() === '!displayroles') {
        if (args.length < 2) {
            writeToLog(`Invalid !displayroles command from ${message.author.id}: ${message.content}`);
            return message.reply('Usage: !displayroles <event_id>');
        }

        const eventId = args[1];
        displayRolesAndClasses(message, eventId);
    }

    // !rsvp <event_id> <status>
    if (args[0].toLowerCase() === '!rsvp') {
        if (args.length < 3) {
            writeToLog(`Invalid !rsvp command from ${message.author.id}: ${message.content}`);
            return message.reply('Usage: !rsvp <event_id> <Attending|Tentative|Declined>');
        }
        const eventId = args[1];
        const status = args[2];
        handleRSVP(message, eventId, message.author.id, status);
    }

    // !showeventroles <event_id>
    if (args[0].toLowerCase() === '!showeventroles') {
        if (args.length < 2) {
            writeToLog(`Invalid !showeventroles command from ${message.author.id}: ${message.content}`);
            return message.reply('Usage: !showeventroles <event_id>');
        }
        const eventId = args[1];
        showEventRoles(message, eventId);
    }
});

// Event listener for when the client is ready
client.once('ready', () => {
    console.log(`Logged in as ${client.user.tag}!`);
    writeToLog(`Bot logged in as ${client.user.tag}!`); // This confirms successful Discord connection
    
    // Initial cleanup of old logs on bot start
    cleanupOldLogs();
    
    // Schedule daily cleanup of old logs (every 24 hours)
    setInterval(cleanupOldLogs, 24 * 60 * 60 * 1000); // 24 hours in milliseconds
});

// Log in to Discord with your client's token
client.login(process.env.DISCORD_TOKEN);

