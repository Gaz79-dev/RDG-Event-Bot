// Replace the entire 'sendBtn.addEventListener' block in your main-v2.js

sendBtn.addEventListener('click', async () => {
    const selectedChannelId = channelDropdown.value;
    const eventId = eventDropdown.value;
    
    if (!selectedChannelId || currentSquads.length === 0) {
        alert('Please select a channel and build squads first.');
        return;
    }
    
    sendBtn.textContent = 'Sending...';
    sendBtn.disabled = true;
    
    try {
        const response = await fetch('/api/events/send-embed', {
            method: 'POST',
            headers: { ...headers, 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_id: selectedChannelId, squads: currentSquads })
        });
        
        if (!response.ok) {
            // ** This new block will log the specific 422 error details **
            if (response.status === 422) {
                const errorData = await response.json();
                console.error("--- 422 VALIDATION ERROR ---");
                console.error("The server rejected the data. Details:", errorData);
                alert("A data validation error occurred. See the F12 console for the exact details.");
            } else {
                handleApiError(response); // Handle other errors like 401, 500, etc.
            }
            throw new Error(`Server responded with status: ${response.status}`);
        }
        
        alert('Squad embed sent successfully!');
        await releaseLock(eventId);
        setLockedState(true, 'Squads sent. This event is now read-only.');

    } catch (error) {
        // This will catch the error thrown above and prevent duplicate alerts.
        console.error("Error in sendBtn listener:", error.message);
    } finally {
        sendBtn.textContent = 'Send to Discord Channel';
        sendBtn.disabled = false;
    }
});
