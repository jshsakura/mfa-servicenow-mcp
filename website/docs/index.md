---
hide:
  - navigation
  - toc
---

<div class="hero-container">
  <h1 class="hero-title">MFA ServiceNow MCP</h1>
  <p class="hero-subtitle">
    The next-generation, MFA-first integration server that empowers your AI agents with 
    <b>secure, high-performance</b> ServiceNow access.
  </p>
  
  <div class="hero-buttons">
    <a href="docs/CLIENT_SETUP.md" class="md-button md-button--primary">
      <span class="twemoji">🚀</span> Get Started Now
    </a>
    <a href="https://github.com/jshsakura/mfa-servicenow-mcp" class="md-button">
      <span class="twemoji">⭐</span> View on GitHub
    </a>
  </div>

  <div class="hero-terminal">
    <div class="hero-terminal-header">
      <div class="hero-terminal-dot red"></div>
      <div class="hero-terminal-dot yellow"></div>
      <div class="hero-terminal-dot green"></div>
    </div>
    <div class="hero-terminal-body">
      <div class="hero-terminal-line">
        <span class="hero-terminal-prompt">➜</span>
        <span class="hero-terminal-command">uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp</span>
      </div>
      <div class="hero-terminal-line">
        <span class="hero-terminal-output">[INFO] Starting MFA ServiceNow MCP Server...</span>
      </div>
      <div class="hero-terminal-line">
        <span class="hero-terminal-output">[INFO] Initializing Playwright browser for MFA...</span>
      </div>
      <div class="hero-terminal-line">
        <span class="hero-terminal-success">✔ Authenticated successfully with ServiceNow</span>
      </div>
      <div class="hero-terminal-line">
        <span class="hero-terminal-prompt">Claude ➜</span>
        <span class="hero-terminal-command">"Create an incident for the database outage"</span>
      </div>
      <div class="hero-terminal-line">
        <span class="hero-terminal-success">✔ [Tool Executed: sn_create_incident] Incident INC001234 created.</span>
      </div>
    </div>
  </div>
</div>

<div class="grid cards" markdown>

-   :material-security:{ .lg .middle } __Secure by Design__

    Built from the ground up to support modern MFA (Multi-Factor Authentication) workflows required by enterprise ServiceNow instances.

-   :material-lightning-bolt:{ .lg .middle } __High Performance__

    Batch processing, smart caching, and token-optimized responses minimize latency and API costs for your LLM agents.

-   :material-toy-brick-outline:{ .lg .middle } __Modular Skills__

    Extend functionality seamlessly with modular skills for Incidents, Changes, Catalog, and Workflow management.

-   :material-auto-fix:{ .lg .middle } __AI Optimized__

    Rich tool metadata and JSON-fast responses designed specifically for Claude, OpenAI, and other LLM agents.

</div>

<div style="margin-top: 60px; text-align: center; padding: 40px; background: var(--md-primary-fg-color--transparent); border-radius: 30px;">
  <h2 style="font-weight: 700;">Ready to transform your ServiceNow workflow?</h2>
  <p style="margin-bottom: 30px;">Connect your AI agents to ServiceNow securely and efficiently.</p>
  <a href="docs/CLIENT_SETUP.md" class="md-button md-button--primary">Read the Setup Guide</a>
</div>
