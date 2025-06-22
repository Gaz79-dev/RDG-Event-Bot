const { Client, GatewayIntentBits, EmbedBuilder } = require('discord.js');
const dotenv = require('dotenv');
const moment = require('moment');

dotenv.config();

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildMembers
    ]
});

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
};

// Command to create a primary role with classes and emojis
const createPrimaryRole = (message, eventId, primaryRole, primaryRoleEmoji, classesWithEmojis) => {
    if (!events[eventId]) {
        return message.reply('Event not found!');
    }

    // Ensure the role doesn't already exist
    if (events[eventId].roles.some(role => role.primaryRole === primaryRole)) {
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
};

// Command to assign a class with emoji to a user for a given event
const assignClassToUser = (message, eventId, userId, primaryRole, className) => {
    if (!events[eventId]) {
        return message.reply('Event not found!');
    }

    // Check if the primary role exists
    const role = events[eventId].roles.find(role => role.primaryRole === primaryRole);
    if (!role) {
        return message.reply(`Primary role "${primaryRole}" not found in event "${events[eventId].title}"`);
    }

    // Check if the class exists under the primary role
    const classObj = role.classes.find(c => c.className === className);
    if (!classObj) {
        return message.reply(`Class "${className}" not found under role "${primaryRole}"`);
    }

    // Add the user to the event with the specified role and class
    const attendee = events[eventId].attendees.find(a => a.userId === userId);
    if (!attendee) {
        events[eventId].attendees.push({ userId, primaryRole, className, emoji: classObj.emoji, rsvpStatus: 'Tentative' });
    } else {
        attendee.primaryRole = primaryRole;
        attendee.className = className;
        attendee.emoji = classObj.emoji;
    }

    message.reply(`User <@${userId}> assigned to "${primaryRole} - ${className}" with emoji "${classObj.emoji}" in event "${events[eventId].title}"`);
};

// Command to display the roles and classes with emojis for an event
const displayRolesAndClasses = (message, eventId) => {
    if (!events[eventId]) {
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
};

// Command to handle RSVP (attending with primary roles and classes)
const handleRSVP = (message, eventId, userId, status) => {
    if (!events[eventId]) {
        return message.reply('Event not found!');
    }

    const event = events[eventId];
    const attendee = event.attendees.find(a => a.userId === userId);
    if (!attendee) {
        return message.reply('You are not signed up for this event!');
    }

    // Update RSVP status
    attendee.rsvpStatus = status;
    message.reply(`RSVP status for <@${userId}> updated to: ${status}`);
};

// Command to show the breakdown of users with roles and emojis
const showEventRoles = (message, eventId) => {
    if (!events[eventId]) {
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
};

// Event creation command
client.on('messageCreate', async (message) => {
    if (message.author.bot) return;

    const args = message.content.split(' ');

    // !createevent <title> <YYYY-MM-DD> <HH:MM> <description> <image_url>
    if (args[0].toLowerCase() === '!createevent') {
        if (args.length < 6) {
            return message.reply('Usage: !createevent <title> <YYYY-MM-DD> <HH:MM> <description> <image_url>');
        }

        const [title, date, time, ...descriptionParts] = args.slice(1);
        const description = descriptionParts.join(' ');
        const dateTime = `${date} ${time}`;

        createEvent(message.channel, title, dateTime, description, args[args.length - 1]);
        message.reply(`Event "${title}" created!`);
    }

    // !createprimaryrole <event_id> <primary_role> <emoji> <class1_emoji class1, class2_emoji class2,...>
    if (args[0].toLowerCase() === '!createprimaryrole') {
        if (args.length < 4) {
            return message.reply('Usage: !createprimaryrole <event_id> <primary_role> <emoji> <class1_emoji class1,class2_emoji class2,...>');
        }

        const eventId = args[1];
        const primaryRole = args[2];
        const primaryRoleEmoji = args[3];
        const classesWithEmojis = args.slice(4);

        createPrimaryRole(message, eventId, primaryRole, primaryRoleEmoji, classesWithEmojis);
    }

    // !assignclass <event_id> <user_id> <primary_role> <class_name>
    if (args[0].toLowerCase() === '!assignclass') {
        if (args.length < 5) {
            return message.reply('Usage: !assignclass <event_id> <user_id> <primary_role> <class_name>');
        }

        const eventId = args[1];
        const userId = args[2].replace(/[<@!>]/g, '');  // Remove @ and <> symbols
        const primaryRole = args[3];
        const className = args[4];

        assignClassToUser(message, eventId, userId, primaryRole, className);
    }

    // !displayroles <event_id>
    if (args[0].toLowerCase() === '!displayroles') {
        if (args.length < 2) {
            return message.reply('Usage: !displayroles <event_id>');
        }

        const eventId = args[1];
        displayRolesAndClasses(message, eventId);
   
