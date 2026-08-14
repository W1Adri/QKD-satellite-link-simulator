// Debug script to check play button functionality
console.log('=== Play Button Debug ===');

setTimeout(() => {
    const btnPlay = document.getElementById('btnPlay');
    const btnPause = document.getElementById('btnPause');
    
    console.log('btnPlay element:', btnPlay);
    console.log('btnPause element:', btnPause);
    
    if (btnPlay) {
        console.log('btnPlay listeners:', getEventListeners(btnPlay));
        
        // Test click
        btnPlay.addEventListener('click', () => {
            console.log('DEBUG: Play button clicked!');
            console.log('state.time.playing before:', window.state?.time?.playing);
        });
    }
    
    // Check if state is accessible
    if (window.state) {
        console.log('state.time:', window.state.time);
        console.log('state.time.playing:', window.state.time.playing);
        console.log('state.time.timeline.length:', window.state.time.timeline.length);
    } else {
        console.log('window.state is not available');
    }
}, 2000);
