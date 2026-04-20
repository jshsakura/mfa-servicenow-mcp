document.addEventListener('DOMContentLoaded', () => {
    /* ========================================================================
       1. INTERSECTION OBSERVER FOR REVEAL ANIMATIONS
       ======================================================================== */
    const revealElements = document.querySelectorAll('.reveal, .reveal-left, .reveal-right, .reveal-stagger');
    
    const revealObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('active');
                
                // If staggered, set custom delay properties for children
                if (entry.target.classList.contains('reveal-stagger')) {
                    const children = entry.target.children;
                    for (let i = 0; i < children.length; i++) {
                        children[i].style.setProperty('--i', i);
                    }
                }
                
                // Optional: stop observing once revealed
                observer.unobserve(entry.target);
            }
        });
    }, {
        root: null,
        rootMargin: '0px',
        threshold: 0.15
    });
    
    revealElements.forEach(el => revealObserver.observe(el));

    /* ========================================================================
       2. MOUSE TRACKING GLOW & TILT EFFECTS FOR CARDS
       ======================================================================== */
    const cards = document.querySelectorAll('.step-card, .hero-terminal, .grid.cards > ul > li');
    
    cards.forEach(card => {
        card.addEventListener('mousemove', e => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            // Set variables for CSS glow
            card.style.setProperty('--mouse-x', `${x}px`);
            card.style.setProperty('--mouse-y', `${y}px`);
            
            // Calculate tilt
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;
            const rotateX = ((y - centerY) / centerY) * -4; // Max rotation 4deg
            const rotateY = ((x - centerX) / centerX) * 4;
            
            card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
            card.style.transition = 'none'; // remove transition for smooth tracking
        });
        
        card.addEventListener('mouseleave', () => {
            card.style.transform = `perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)`;
            card.style.transition = 'transform 0.5s ease, box-shadow 0.5s ease'; // restore transition
        });
    });

    /* ========================================================================
       3. HERO CANVAS PARTICLES (Constellation Effect)
       ======================================================================== */
    const heroSection = document.querySelector('.hero-section');
    if (heroSection) {
        const canvas = document.createElement('canvas');
        canvas.id = 'hero-canvas';
        canvas.style.position = 'absolute';
        canvas.style.top = '0';
        canvas.style.left = '0';
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.pointerEvents = 'none';
        canvas.style.zIndex = '1'; // Above bg, below content
        canvas.style.opacity = '0.6';
        
        // Insert before hero-content
        const heroContent = heroSection.querySelector('.hero-content');
        if (heroContent) {
            heroSection.insertBefore(canvas, heroContent);
        } else {
            heroSection.appendChild(canvas);
        }
        
        const ctx = canvas.getContext('2d');
        let particles = [];
        let w, h;
        
        const initCanvas = () => {
            w = canvas.width = heroSection.offsetWidth;
            h = canvas.height = heroSection.offsetHeight;
            particles = [];
            const numParticles = Math.min(Math.floor(w * h / 10000), 100);
            
            for (let i = 0; i < numParticles; i++) {
                particles.push({
                    x: Math.random() * w,
                    y: Math.random() * h,
                    vx: (Math.random() - 0.5) * 0.5,
                    vy: (Math.random() - 0.5) * 0.5,
                    radius: Math.random() * 2 + 1
                });
            }
        };
        
        const animateParticles = () => {
            ctx.clearRect(0, 0, w, h);
            
            const scheme = document.body.getAttribute('data-md-color-scheme') || 'default';
            const isDark = scheme === 'slate';
            const color = isDark ? '255, 255, 255' : '99, 102, 241';
            
            particles.forEach((p, index) => {
                p.x += p.vx;
                p.y += p.vy;
                
                if (p.x < 0 || p.x > w) p.vx *= -1;
                if (p.y < 0 || p.y > h) p.vy *= -1;
                
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(${color}, 0.5)`;
                ctx.fill();
                
                // Draw lines between close particles
                for (let j = index + 1; j < particles.length; j++) {
                    const p2 = particles[j];
                    const dx = p.x - p2.x;
                    const dy = p.y - p2.y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    
                    if (dist < 120) {
                        ctx.beginPath();
                        ctx.moveTo(p.x, p.y);
                        ctx.lineTo(p2.x, p2.y);
                        ctx.strokeStyle = `rgba(${color}, ${0.2 - (dist / 120) * 0.2})`;
                        ctx.lineWidth = 1;
                        ctx.stroke();
                    }
                }
            });
            requestAnimationFrame(animateParticles);
        };
        
        initCanvas();
        animateParticles();
        
        window.addEventListener('resize', initCanvas);
    }

    /* ========================================================================
       4. TYPED TERMINAL EFFECT
       ======================================================================== */
    const terminalBody = document.getElementById('hero-typed-terminal');
    if (terminalBody) {
        const lines = [
            { type: 'command', text: 'uvx mfa-servicenow-mcp --help' },
            { type: 'success', text: 'Loaded MFA ServiceNow MCP Server v1.0' },
            { type: 'thinking', text: 'Analyzing database schema...' },
            { type: 'tool', text: 'Tool call: [search_catalog_items]' },
            { type: 'text', text: 'Found 12 related items in Service Catalog.' },
            { type: 'command', text: 'mcp-server process --query "Fix incident INC001"' },
            { type: 'thinking', text: 'Retrieving incident details...' },
            { type: 'success', text: 'Incident resolved successfully. Updating records.' },
            { type: 'prompt', text: '_' }
        ];
        
        let lineIndex = 0;
        let charIndex = 0;
        let currentLineElement = null;
        
        const typeChar = () => {
            if (lineIndex >= lines.length) {
                // Done typing, blink cursor on the last line forever
                return;
            }
            
            const line = lines[lineIndex];
            
            if (charIndex === 0) {
                // Create new line element
                currentLineElement = document.createElement('div');
                currentLineElement.className = 'hero-terminal-line';
                
                if (line.type === 'command') {
                    const prompt = document.createElement('span');
                    prompt.className = 'hero-terminal-prompt';
                    prompt.textContent = '$';
                    currentLineElement.appendChild(prompt);
                    
                    const cmd = document.createElement('span');
                    cmd.className = 'hero-terminal-command';
                    currentLineElement.appendChild(cmd);
                } else if (line.type !== 'prompt') {
                    currentLineElement.className += ` hero-terminal-${line.type}`;
                }
                
                terminalBody.appendChild(currentLineElement);
                terminalBody.scrollTop = terminalBody.scrollHeight;
            }
            
            if (line.type === 'prompt') {
                const cursor = document.createElement('span');
                cursor.className = 'hero-terminal-cursor';
                currentLineElement.appendChild(cursor);
                lineIndex++;
                charIndex = 0;
                setTimeout(typeChar, 500);
                return;
            }
            
            // Append character based on type
            let textContainer = currentLineElement;
            if (line.type === 'command') {
                textContainer = currentLineElement.querySelector('.hero-terminal-command');
            }
            
            textContainer.textContent += line.text.charAt(charIndex);
            charIndex++;
            
            if (charIndex < line.text.length) {
                // Random typing speed delay
                setTimeout(typeChar, line.type === 'command' ? Math.random() * 50 + 20 : 10);
            } else {
                // Line finished
                lineIndex++;
                charIndex = 0;
                setTimeout(typeChar, line.type === 'command' ? 400 : 200);
            }
        };
        
        // Start typing effect after a small delay
        setTimeout(typeChar, 800);
    }
    
    /* ========================================================================
       5. INSTALL TABS (Simple Toggle)
       ======================================================================== */
    const installTabs = document.querySelectorAll('.install-tab');
    installTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Remove active from all tabs in the same block
            const block = tab.closest('.install-block');
            block.querySelectorAll('.install-tab').forEach(t => t.classList.remove('active'));
            block.querySelectorAll('.install-panel').forEach(p => p.classList.remove('active'));
            
            // Add active to clicked
            tab.classList.add('active');
            const targetId = tab.getAttribute('data-target');
            const targetPanel = block.querySelector(`#${targetId}`);
            if (targetPanel) {
                targetPanel.classList.add('active');
            }
        });
    });
});