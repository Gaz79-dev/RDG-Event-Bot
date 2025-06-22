const { Client, GatewayIntentBits, EmbedBuilder } = require('discord.js');
const dotenv = require('dotenv');
const moment = require('moment');
const winston = require('winston');
const { transports } = winston;
const { format } = require('logform');
const path = require('path');
const fs = require('fs');

// Load environment variables
dotenv.config();

// Create a directory for logs if it doesn't exist
const logDir = path.join(__dirname, 'logs');
if (!fs.existsSync(logDir)) {
    fs.mkdirSync(logDir);
}

// Create a logger with daily rotation
const logTransport = new transports.DailyRotateFile({
    filename: path.join(logDir, 'log-%DATE%.log'),
    datePattern: 'YYYY-MM-DD',
    maxSize: '20m',
    maxFiles: '5d', // Keep logs for the last 5 days
});

const logger = winston.createLogger({
    level: 'info',
    format: format.combine(
        format.colorize(),
        format.timestamp(),
        format.printf(({ timestamp, level, message }) => {
            return `${timestamp} ${level}: ${message}`;
        })
    ),
    transports: [
        new transports.Console(),
        logTransport,
    ],
});

// Discord client setup
const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildMembers
    ]
});

// Store events and roles in memory
let events = {};
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
        roles: [],
    };

    const embed = new EmbedBuilder()
        .setTitle(`Event: ${title}`)
        .setDescription(description)
        .setImage(imageUrl)
        .addFields(
            { name: 'Date & Time', value: moment(dateTime).format('YYYY-MM-DD HH:mm') }
        );
    channel.send({ embeds: [embed] });

    logger.info(`Event "${title}" created at ${moment(dateTime).format('YYYY-MM-DD HH:mm')}`);
};

// Connection check and log
client.once('ready', () => {
    logger.info(`Bot connected to Discord as ${client.user.tag}`);
});

// Command to handle event creation
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
        logger.info(`Command !createevent executed by ${message.author.tag}`);
    }

    // !createprimaryrole <event_id> <primary_role> <emoji> <class1_emoji class1,class2_emoji class2,...>
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

    // Additional event-related commands...
});

// Handle primary role creation with classes
const createPrimaryRole = (message, eventId, primaryRole, primaryRoleEmoji, classesWithEmojis) => {
    if (!events[eventId]) {
        return message.reply('Event not found!');
    }

    if (events[eventId].roles.some(role => role.primaryRole === primaryRole)) {
        return message.reply('This primary role already exists!');
    }

    const classes = classesWithEmojis.map(classWithEmoji => {
        const [emoji, ...classParts] = classWithEmoji.split(' ');
        const className = classParts.join(' ');
        return { className, emoji };
    });

    events[eventId].roles.push({ primaryRole, emoji: primaryRoleEmoji, classes });
    message.reply(`Primary Role "${primaryRole}" created with emoji "${primaryRoleEmoji}" and classes: [${classes.map(c => `${c.emoji} ${c.className}`).join(', ')}]`);
    logger.info(`Primary Role "${primaryRole}" with emoji "${primaryRoleEmoji}" created for event "${events[eventId].title}"`);
};

// Start the bot
client.login(process.env.DISCORD_TOKEN);
