/* ============================================================
   AI Agent Marketplace -- Frontend Application
   ============================================================
   Single-page application with hash-based routing.
   Pages: Auth, Marketplace, My Agents, Workspace, Pipelines
   
   Features:
     - Agent Card display with URLs for integration
     - Tabbed agent cards: Run / Integrate / Code
     - Auto-generated code snippets (Python, curl, JS)
     - Protocol badges (A2A / MCP ready)
   ============================================================ */

// ==============================================================================
// API CLIENT
// ==============================================================================
const API = {
    base: window.location.origin + '/api',

    getToken() { return localStorage.getItem('token'); },
    setToken(t) { localStorage.setItem('token', t); },
    clearToken() { localStorage.removeItem('token'); },

    async request(method, path, body = null) {
        const headers = { 'Content-Type': 'application/json' };
        const token = this.getToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const opts = { method, headers };
        if (body) opts.body = JSON.stringify(body);

        const res = await fetch(this.base + path, opts);
        const data = await res.json();
        if (res.status === 401 && path !== '/auth/login') {
            this.clearToken();
            App.state.user = null;
            App.navigate('login');
        }
        return { ok: res.ok, status: res.status, data };
    },

    get(p) { return this.request('GET', p); },
    post(p, b) { return this.request('POST', p, b); },
    delete(p) { return this.request('DELETE', p); },
};


// ==============================================================================
// TOAST NOTIFICATIONS
// ==============================================================================
function showToast(message, type = 'info') {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}


// ==============================================================================
// APP STATE & ROUTING
// ==============================================================================
const App = {
    state: {
        user: null,
        marketplaceAgents: [],
        myAgents: [],
        pipelines: [],
        currentAgent: null,
        pipelineSteps: [],
        activeAgentTabs: {},   // agentId -> active tab name
        snippetsCache: {},     // agentId -> snippets data
    },

    async init() {
        window.addEventListener('hashchange', () => this.route());
        // Check for existing token
        if (API.getToken()) {
            const res = await API.get('/auth/me');
            if (res.ok) {
                this.state.user = res.data.user;
            } else {
                API.clearToken();
            }
        }
        this.route();
    },

    navigate(page) {
        window.location.hash = '#' + page;
    },

    route() {
        const hash = window.location.hash.slice(1) || '';
        const [page, ...params] = hash.split('/');

        if (!this.state.user && !['login', 'register'].includes(page)) {
            this.navigate('login');
            return;
        }
        if (this.state.user && ['login', 'register', ''].includes(page)) {
            this.navigate('marketplace');
            return;
        }

        switch (page) {
            case 'login': this.renderLogin(); break;
            case 'register': this.renderRegister(); break;
            case 'marketplace': this.renderMarketplace(); break;
            case 'my-agents': this.renderMyAgents(); break;
            case 'workspace': this.renderWorkspace(params[0]); break;
            case 'pipelines': this.renderPipelines(); break;
            case 'pipeline-builder': this.renderPipelineBuilder(params[0]); break;
            case 'pipeline-run': this.renderPipelineRun(params[0]); break;
            case 'tools': this.renderTools(); break;
            case 'tool-run': this.renderToolRunner(params[0]); break;
            default: this.navigate(this.state.user ? 'marketplace' : 'login');
        }
    },

    render(html) {
        document.getElementById('app').innerHTML = html;
    },

    // -- Navbar ---------------------------------------------------------------
    navbar(activePage) {
        const u = this.state.user;
        return `
        <nav class="navbar">
            <div class="nav-brand" onclick="App.navigate('marketplace')">
                <div class="nav-brand-icon">A</div>
                <div class="nav-brand-text"><span>AgentForge</span></div>
            </div>
            <div class="nav-links">
                <button class="nav-link ${activePage === 'marketplace' ? 'active' : ''}" onclick="App.navigate('marketplace')">Marketplace</button>
                <button class="nav-link ${activePage === 'my-agents' ? 'active' : ''}" onclick="App.navigate('my-agents')">My Agents</button>
                <button class="nav-link ${activePage === 'tools' ? 'active' : ''}" onclick="App.navigate('tools')">Tools</button>
                <button class="nav-link ${activePage === 'pipelines' ? 'active' : ''}" onclick="App.navigate('pipelines')">Pipelines</button>
            </div>
            <div class="nav-right">
                <div class="credits-badge">${u.credits} credits</div>
                <button class="btn-logout" onclick="App.logout()">Logout</button>
            </div>
        </nav>`;
    },

    async logout() {
        API.clearToken();
        this.state.user = null;
        this.navigate('login');
    },


    // =========================================================================
    // AUTH PAGES
    // =========================================================================
    renderLogin() {
        this.render(`
        <div class="auth-container">
            <div class="auth-card">
                <h2>Welcome Back</h2>
                <p class="subtitle">Sign in to access your agents</p>
                <div id="auth-error"></div>
                <div class="form-group">
                    <label class="form-label">Username</label>
                    <input class="form-input" id="login-user" type="text" placeholder="Enter your username" autocomplete="username">
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <input class="form-input" id="login-pass" type="password" placeholder="Enter your password" autocomplete="current-password">
                </div>
                <button class="btn btn-primary btn-full" id="login-btn" onclick="App.doLogin()">Sign In</button>
                <p class="auth-toggle">Don't have an account? <a onclick="App.navigate('register')">Create one</a></p>
            </div>
        </div>`);
        document.getElementById('login-user').focus();
        document.getElementById('login-pass').addEventListener('keydown', e => { if (e.key === 'Enter') App.doLogin(); });
    },

    renderRegister() {
        this.render(`
        <div class="auth-container">
            <div class="auth-card">
                <h2>Create Account</h2>
                <p class="subtitle">Get 100 free credits to start</p>
                <div id="auth-error"></div>
                <div class="form-group">
                    <label class="form-label">Username</label>
                    <input class="form-input" id="reg-user" type="text" placeholder="Choose a username" autocomplete="username">
                </div>
                <div class="form-group">
                    <label class="form-label">Email</label>
                    <input class="form-input" id="reg-email" type="email" placeholder="your@email.com" autocomplete="email">
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <input class="form-input" id="reg-pass" type="password" placeholder="Min 6 characters" autocomplete="new-password">
                </div>
                <button class="btn btn-primary btn-full" onclick="App.doRegister()">Create Account</button>
                <p class="auth-toggle">Already have an account? <a onclick="App.navigate('login')">Sign in</a></p>
            </div>
        </div>`);
        document.getElementById('reg-user').focus();
    },

    async doLogin() {
        const username = document.getElementById('login-user').value.trim();
        const password = document.getElementById('login-pass').value;
        if (!username || !password) return showToast('Fill in all fields', 'error');

        const btn = document.getElementById('login-btn');
        btn.disabled = true;
        btn.textContent = 'Signing in...';

        const res = await API.post('/auth/login', { username, password });
        if (res.ok) {
            API.setToken(res.data.token);
            this.state.user = res.data.user;
            showToast(`Welcome back, ${username}!`, 'success');
            this.navigate('marketplace');
        } else {
            document.getElementById('auth-error').innerHTML = `<div class="alert alert-error">${res.data.error}</div>`;
            btn.disabled = false;
            btn.textContent = 'Sign In';
        }
    },

    async doRegister() {
        const username = document.getElementById('reg-user').value.trim();
        const email = document.getElementById('reg-email').value.trim();
        const password = document.getElementById('reg-pass').value;
        if (!username || !email || !password) return showToast('Fill in all fields', 'error');

        const res = await API.post('/auth/register', { username, email, password });
        if (res.ok) {
            API.setToken(res.data.token);
            this.state.user = res.data.user;
            showToast(res.data.message, 'success');
            this.navigate('marketplace');
        } else {
            document.getElementById('auth-error').innerHTML = `<div class="alert alert-error">${res.data.error}</div>`;
        }
    },


    // =========================================================================
    // MARKETPLACE PAGE
    // =========================================================================
    async renderMarketplace() {
        this.render(this.navbar('marketplace') + `
        <div class="page">
            <div class="page-header">
                <h1 class="page-title">Agent Marketplace</h1>
                <p class="page-subtitle">Discover and purchase powerful AI agents — connect via A2A protocol or future MCP tools</p>
            </div>
            <div class="agents-grid" id="agents-grid">
                <div class="loading"><div class="spinner"></div> Loading agents...</div>
            </div>
        </div>`);

        // Fetch marketplace + my agents
        const [mktRes, myRes] = await Promise.all([
            API.get('/marketplace'),
            API.get('/my-agents'),
        ]);

        const agents = mktRes.ok ? mktRes.data.agents : [];
        const owned = myRes.ok ? myRes.data.agents.map(a => a.id) : [];
        this.state.marketplaceAgents = agents;

        const grid = document.getElementById('agents-grid');
        if (!agents.length) {
            grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">~</div><h3>No agents available</h3><p>Check back later for new agents.</p></div>';
            return;
        }

        grid.innerHTML = agents.map(a => {
            const isOwned = owned.includes(a.id);
            const tags = (a.tags || []).slice(0, 4).map(t => `<span class="tag">${t}</span>`).join('');
            const protocolType = a.agent_type || 'a2a';
            const protocolLabel = protocolType === 'mcp' ? 'MCP' : 'A2A';
            return `
            <div class="agent-card" style="--card-accent: ${a.color}">
                <div class="agent-card-header">
                    <div class="agent-icon" style="background: linear-gradient(135deg, ${a.color}, ${a.color}88)">${a.icon}</div>
                    <div class="agent-card-info">
                        <div class="agent-card-name">
                            ${a.name}
                            <span class="protocol-badge ${protocolType}">${protocolLabel}</span>
                        </div>
                        <div class="agent-card-tagline">${a.tagline}</div>
                    </div>
                </div>
                <div class="agent-card-body">
                    <p class="agent-card-desc">${a.description}</p>
                </div>
                <div class="agent-card-tags">${tags}</div>
                <div class="agent-card-footer">
                    <div>
                        <div class="agent-price">${a.price} <span>credits</span></div>
                        <div class="agent-status">
                            <span class="status-dot ${a.online ? 'online' : 'offline'}"></span>
                            ${a.online ? 'Online' : 'Offline'}
                        </div>
                    </div>
                    ${isOwned
                        ? `<div style="display:flex;gap:8px;align-items:center">
                             <span class="owned-badge">Owned</span>
                             <button class="btn btn-secondary btn-sm" onclick="App.navigate('my-agents')">Connect</button>
                           </div>`
                        : `<button class="btn btn-primary btn-sm" onclick="App.purchaseAgent('${a.id}')">Purchase</button>`
                    }
                </div>
            </div>`;
        }).join('');
    },

    async purchaseAgent(agentId) {
        const res = await API.post('/purchase', { agent_id: agentId });
        if (res.ok) {
            this.state.user.credits = res.data.remaining_credits;
            showToast(res.data.message, 'success');
            this.renderMarketplace();
        } else {
            showToast(res.data.error, 'error');
        }
    },


    // =========================================================================
    // MY AGENTS PAGE — Tabbed Agent Cards
    // =========================================================================
    async renderMyAgents() {
        this.render(this.navbar('my-agents') + `
        <div class="page">
            <div class="page-header">
                <h1 class="page-title">My Agents</h1>
                <p class="page-subtitle">Run agents directly, view Agent Cards, or grab integration code for your own projects</p>
            </div>
            <div class="my-agents-grid" id="my-agents-grid">
                <div class="loading"><div class="spinner"></div> Loading...</div>
            </div>
        </div>`);

        const res = await API.get('/my-agents');
        const agents = res.ok ? res.data.agents : [];
        this.state.myAgents = agents;

        const grid = document.getElementById('my-agents-grid');
        if (!agents.length) {
            grid.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1">
                <div class="empty-state-icon">~</div>
                <h3>No agents purchased yet</h3>
                <p>Visit the marketplace to discover and purchase AI agents.</p>
                <button class="btn btn-primary" style="margin-top:16px" onclick="App.navigate('marketplace')">Browse Marketplace</button>
            </div>`;
            return;
        }

        // Initialize active tabs
        agents.forEach(a => {
            if (!this.state.activeAgentTabs[a.id]) this.state.activeAgentTabs[a.id] = 'run';
        });

        grid.innerHTML = agents.map(a => this.renderMyAgentCard(a)).join('');
    },

    renderMyAgentCard(a) {
        const activeTab = this.state.activeAgentTabs[a.id] || 'run';
        const protocolType = a.agent_type || 'a2a';
        const protocolLabel = protocolType === 'mcp' ? 'MCP' : 'A2A';

        return `
        <div class="my-agent-card" style="--card-accent: ${a.color}" id="agent-card-${a.id}">
            <!-- Header -->
            <div class="my-agent-header">
                <div class="agent-icon" style="background: linear-gradient(135deg, ${a.color}, ${a.color}88)">${a.icon}</div>
                <div class="my-agent-header-info">
                    <h3>
                        ${a.name}
                        <span class="protocol-badge ${protocolType}">${protocolLabel}</span>
                    </h3>
                    <div class="tagline">${a.tagline}</div>
                </div>
                <div class="my-agent-header-status">
                    <div class="agent-status">
                        <span class="status-dot ${a.online ? 'online' : 'offline'}"></span>
                        ${a.online ? 'Online' : 'Offline'}
                    </div>
                </div>
            </div>

            <!-- Tabs -->
            <div class="card-tabs">
                <button class="card-tab ${activeTab === 'run' ? 'active' : ''}" onclick="App.switchAgentTab('${a.id}', 'run')">▶ Run</button>
                <button class="card-tab ${activeTab === 'integrate' ? 'active' : ''}" onclick="App.switchAgentTab('${a.id}', 'integrate')">🔗 Integrate</button>
                <button class="card-tab ${activeTab === 'code' ? 'active' : ''}" onclick="App.switchAgentTab('${a.id}', 'code')">{ } Code</button>
            </div>

            <!-- Tab: Run -->
            <div class="card-tab-content ${activeTab === 'run' ? 'active' : ''}" id="tab-run-${a.id}">
                <div class="inline-runner">
                    <div class="form-group" style="margin-bottom:0">
                        <label class="form-label">Input</label>
                        <textarea class="form-input" id="runner-input-${a.id}" placeholder="Enter your query or topic..." rows="3"></textarea>
                    </div>
                    <div style="display:flex;gap:8px;align-items:center">
                        <button class="btn btn-primary btn-sm" id="runner-btn-${a.id}" onclick="App.runAgentInline('${a.id}')" ${!a.online ? 'disabled' : ''}>
                            Run Agent
                        </button>
                        <button class="btn btn-secondary btn-sm" onclick="App.navigate('workspace/${a.id}')">
                            Full Workspace →
                        </button>
                    </div>
                    <div id="runner-output-${a.id}" class="hidden"></div>
                </div>
            </div>

            <!-- Tab: Integrate -->
            <div class="card-tab-content ${activeTab === 'integrate' ? 'active' : ''}" id="tab-integrate-${a.id}">
                <div class="integration-panel">
                    <div class="integration-row">
                        <span class="integration-label">API Key</span>
                        <div class="integration-value">
                            <code class="integration-url" style="color:var(--accent-green);font-size:11px" id="apikey-display-${a.id}">${a.api_key ? a.api_key.slice(0, 6) + '••••••••••••••••••' + a.api_key.slice(-4) : 'N/A'}</code>
                            <button class="btn btn-secondary btn-xs" onclick="App.revealAndCopyKey('${a.id}', '${a.api_key}')">Show & Copy</button>
                            <button class="btn btn-danger btn-xs" onclick="App.regenerateKey('${a.id}')">Regenerate</button>
                        </div>
                    </div>
                    <div class="integration-row">
                        <span class="integration-label">A2A Server</span>
                        <div class="integration-value">
                            <code class="integration-url">${a.a2a_url || 'N/A'}</code>
                            <button class="btn btn-secondary btn-xs" onclick="App.copyText('${a.a2a_url}')">Copy</button>
                        </div>
                    </div>
                    <div class="integration-row">
                        <span class="integration-label">Agent Card</span>
                        <div class="integration-value">
                            <code class="integration-url purple">${a.agent_card_url || 'N/A'}</code>
                            <button class="btn btn-secondary btn-xs" onclick="App.copyText('${a.agent_card_url}')">Copy</button>
                        </div>
                    </div>
                    <div class="integration-row">
                        <span class="integration-label">Protocol</span>
                        <div class="integration-value">
                            <span class="protocol-badge ${protocolType}" style="font-size:11px">${protocolLabel} Protocol</span>
                            <span style="font-size:12px;color:var(--text-tertiary)">— ${protocolType === 'mcp' ? 'Model Context Protocol tools' : 'Agent-to-Agent standard'}</span>
                        </div>
                    </div>

                    <div style="margin-top:8px;padding:10px 14px;background:rgba(255,149,0,0.06);border:1px solid rgba(255,149,0,0.15);border-radius:var(--radius-sm)">
                        <div style="font-size:11px;color:var(--accent-orange);font-weight:600">🔒 SECURITY NOTE</div>
                        <div style="font-size:12px;color:var(--text-secondary);margin-top:4px">Your API key authenticates requests to this agent. Include it as <code style="color:var(--accent-cyan);font-size:11px">X-API-Key</code> header. Never share it publicly.</div>
                    </div>

                    <div style="margin-top:8px">
                        <button class="btn btn-secondary btn-sm" style="width:100%" onclick="App.toggleAgentCardJSON('${a.id}')">
                            View Full Agent Card JSON
                        </button>
                    </div>
                    <div id="card-json-${a.id}" class="hidden"></div>
                </div>
            </div>

            <!-- Tab: Code -->
            <div class="card-tab-content ${activeTab === 'code' ? 'active' : ''}" id="tab-code-${a.id}">
                <div id="snippets-${a.id}">
                    <div class="loading" style="padding:20px"><div class="spinner" style="width:20px;height:20px;border-width:2px"></div> Loading snippets...</div>
                </div>
            </div>
        </div>`;
    },

    switchAgentTab(agentId, tab) {
        this.state.activeAgentTabs[agentId] = tab;

        // Update tab buttons
        const card = document.getElementById(`agent-card-${agentId}`);
        if (!card) return;

        card.querySelectorAll('.card-tab').forEach(t => t.classList.remove('active'));
        card.querySelectorAll('.card-tab-content').forEach(t => t.classList.remove('active'));

        // Activate selected
        const tabs = card.querySelectorAll('.card-tab');
        const contents = card.querySelectorAll('.card-tab-content');
        const tabMap = { run: 0, integrate: 1, code: 2 };
        const idx = tabMap[tab] ?? 0;
        if (tabs[idx]) tabs[idx].classList.add('active');
        if (contents[idx]) contents[idx].classList.add('active');

        // Lazy-load snippets
        if (tab === 'code' && !this.state.snippetsCache[agentId]) {
            this.loadSnippets(agentId);
        }
    },

    // -- Inline Agent Runner --------------------------------------------------
    async runAgentInline(agentId) {
        const inputEl = document.getElementById(`runner-input-${agentId}`);
        const outputEl = document.getElementById(`runner-output-${agentId}`);
        const btnEl = document.getElementById(`runner-btn-${agentId}`);
        if (!inputEl || !outputEl || !btnEl) return;

        const input = inputEl.value.trim();
        if (!input) return showToast('Please enter some input', 'error');

        btnEl.disabled = true;
        btnEl.innerHTML = '<div class="spinner" style="width:14px;height:14px;border-width:2px;margin-right:6px"></div> Running...';

        outputEl.classList.remove('hidden');
        outputEl.innerHTML = '<div class="inline-runner-output"><div class="loading" style="padding:16px"><div class="spinner" style="width:18px;height:18px;border-width:2px"></div> Agent is processing...</div></div>';

        const res = await API.post(`/agents/${agentId}/run`, { input });

        btnEl.disabled = false;
        btnEl.textContent = 'Run Agent';

        if (res.ok && res.data.result) {
            const r = res.data.result;
            if (r.success) {
                const elapsed = r.elapsed_sec ? `<div style="color:var(--text-tertiary);font-size:12px;margin-bottom:8px">Completed in ${r.elapsed_sec}s</div>` : '';
                const clean = { ...r };
                delete clean.success;
                delete clean.elapsed_sec;
                outputEl.innerHTML = `<div class="inline-runner-output">${elapsed}<div class="output-json" style="max-height:300px">${this.syntaxHighlight(JSON.stringify(clean, null, 2))}</div></div>`;
            } else {
                outputEl.innerHTML = `<div class="inline-runner-output"><div class="alert alert-error" style="margin:0">${r.error || 'Agent returned an error.'}</div></div>`;
            }
        } else {
            outputEl.innerHTML = `<div class="inline-runner-output"><div class="alert alert-error" style="margin:0">${res.data.error || 'Request failed.'}</div></div>`;
        }
    },

    // -- Agent Card JSON Viewer -----------------------------------------------
    async toggleAgentCardJSON(agentId) {
        const viewer = document.getElementById(`card-json-${agentId}`);
        if (!viewer) return;

        if (!viewer.classList.contains('hidden')) {
            viewer.classList.add('hidden');
            return;
        }

        viewer.classList.remove('hidden');
        viewer.innerHTML = '<div class="loading" style="padding:16px"><div class="spinner" style="width:18px;height:18px;border-width:2px"></div> Fetching Agent Card...</div>';

        const res = await API.get(`/agents/${agentId}/card`);

        if (res.ok && res.data.agent_card) {
            const card = res.data.agent_card;
            const cardStr = JSON.stringify(card, null, 2);
            viewer.innerHTML = `
            <div class="json-viewer" style="margin-top:12px">
                <div class="json-viewer-header">
                    <span class="json-viewer-title">Agent Card JSON</span>
                    <button class="btn btn-secondary btn-xs" onclick="App.copyText(${JSON.stringify(cardStr).replace(/'/g, "\\'")})">Copy JSON</button>
                </div>
                <div class="output-json" style="max-height:350px;margin:0;border-radius:0">${this.syntaxHighlight(cardStr)}</div>
            </div>`;
        } else {
            viewer.innerHTML = `<div class="alert alert-error" style="margin:12px 0 0">${res.data.error || 'Failed to fetch Agent Card.'}</div>`;
        }
    },

    // -- Code Snippets --------------------------------------------------------
    async loadSnippets(agentId) {
        const container = document.getElementById(`snippets-${agentId}`);
        if (!container) return;

        const res = await API.get(`/agents/${agentId}/snippets`);
        if (!res.ok) {
            container.innerHTML = `<div class="alert alert-error" style="margin:0">${res.data.error || 'Failed to load snippets.'}</div>`;
            return;
        }

        const snippets = res.data.snippets;
        this.state.snippetsCache[agentId] = snippets;

        this.renderSnippets(agentId, snippets);
    },

    renderSnippets(agentId, snippets) {
        const container = document.getElementById(`snippets-${agentId}`);
        if (!container) return;

        const defaultLang = 'python';

        container.innerHTML = `
        <div class="code-block-container">
            <div style="margin-bottom:12px">
                <div style="font-size:12px;font-weight:600;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px">Integration Code</div>
                <div style="font-size:13px;color:var(--text-secondary)">Copy these snippets to integrate this agent into your application</div>
            </div>

            <div class="code-tabs" id="code-tabs-${agentId}">
                <button class="code-tab active" onclick="App.switchCodeTab('${agentId}', 'python')">Python</button>
                <button class="code-tab" onclick="App.switchCodeTab('${agentId}', 'javascript')">JavaScript</button>
                <button class="code-tab" onclick="App.switchCodeTab('${agentId}', 'curl_card')">curl (Card)</button>
                <button class="code-tab" onclick="App.switchCodeTab('${agentId}', 'curl_run')">curl (Run)</button>
            </div>

            <div class="code-block" id="code-content-${agentId}">
                <button class="copy-btn" onclick="App.copySnippet('${agentId}')">Copy</button>
                <pre id="code-pre-${agentId}">${this.escapeHtml(snippets.python || '')}</pre>
            </div>
        </div>

        <div style="margin-top:16px;padding:12px 16px;background:var(--bg-secondary);border:1px solid var(--border-subtle);border-radius:var(--radius-sm)">
            <div style="font-size:12px;font-weight:600;color:var(--text-tertiary);margin-bottom:6px">📦 QUICK START</div>
            <div style="font-size:13px;color:var(--text-secondary);line-height:1.6">
                <strong>1.</strong> Install: <code style="color:var(--accent-cyan);background:var(--bg-primary);padding:2px 6px;border-radius:4px;font-size:12px">pip install python-a2a</code><br>
                <strong>2.</strong> Copy the Python snippet above into your project<br>
                <strong>3.</strong> Run it — the agent is ready to use in your pipeline!
            </div>
        </div>`;
    },

    switchCodeTab(agentId, lang) {
        const snippets = this.state.snippetsCache[agentId];
        if (!snippets) return;

        // Update tab buttons
        const tabContainer = document.getElementById(`code-tabs-${agentId}`);
        if (tabContainer) {
            tabContainer.querySelectorAll('.code-tab').forEach(t => t.classList.remove('active'));
            const tabs = tabContainer.querySelectorAll('.code-tab');
            const langMap = { python: 0, javascript: 1, curl_card: 2, curl_run: 3 };
            const idx = langMap[lang] ?? 0;
            if (tabs[idx]) tabs[idx].classList.add('active');
        }

        // Update code content
        const pre = document.getElementById(`code-pre-${agentId}`);
        if (pre) {
            pre.textContent = snippets[lang] || '// No snippet available';
            // Store current language for copy
            pre.dataset.currentLang = lang;
        }
    },

    copySnippet(agentId) {
        const pre = document.getElementById(`code-pre-${agentId}`);
        if (!pre) return;
        this.copyText(pre.textContent);
    },

    // -- API Key Management ---------------------------------------------------
    revealAndCopyKey(agentId, apiKey) {
        const display = document.getElementById(`apikey-display-${agentId}`);
        if (display) {
            display.textContent = apiKey;
            // Auto-hide after 10 seconds
            setTimeout(() => {
                display.textContent = apiKey.slice(0, 6) + '••••••••••••••••••' + apiKey.slice(-4);
            }, 10000);
        }
        this.copyText(apiKey);
    },

    async regenerateKey(agentId) {
        if (!confirm('Regenerate API key? Your old key will stop working immediately.')) return;

        const res = await API.post(`/agents/${agentId}/regenerate-key`);
        if (res.ok) {
            showToast(res.data.message, 'success');
            // Refresh the page to show the new key
            this.renderMyAgents();
        } else {
            showToast(res.data.error || 'Failed to regenerate key.', 'error');
        }
    },


    // =========================================================================
    // UTILITY FUNCTIONS
    // =========================================================================
    copyText(text) {
        navigator.clipboard.writeText(text).then(() => {
            showToast('Copied to clipboard!', 'success');
        }).catch(() => {
            // Fallback for older browsers
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            showToast('Copied to clipboard!', 'success');
        });
    },

    escapeHtml(str) {
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    syntaxHighlight(json) {
        json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return json.replace(
            /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
            function (match) {
                let cls = 'color:#ae81ff'; // number
                if (/^"/.test(match)) {
                    if (/:$/.test(match)) cls = 'color:#66d9ef'; // key
                    else cls = 'color:#a6e22e'; // string
                } else if (/true|false/.test(match)) cls = 'color:#f92672'; // bool
                else if (/null/.test(match)) cls = 'color:#f92672'; // null
                return '<span style="' + cls + '">' + match + '</span>';
            }
        );
    },

    formatOutput(data) {
        // Clean display of agent output
        const clean = { ...data };
        delete clean.success;
        delete clean.elapsed_sec;

        const elapsed = data.elapsed_sec ? `<div style="color:var(--text-tertiary);font-size:12px;margin-bottom:8px">Completed in ${data.elapsed_sec}s</div>` : '';
        return elapsed + this.syntaxHighlight(JSON.stringify(clean, null, 2));
    },


    // =========================================================================
    // WORKSPACE PAGE -- Use a single agent (full page)
    // =========================================================================
    async renderWorkspace(agentId) {
        if (!agentId) return this.navigate('my-agents');

        // Get agent info
        const res = await API.get(`/marketplace/${agentId}`);
        if (!res.ok) { showToast('Agent not found', 'error'); return this.navigate('my-agents'); }
        const agent = res.data.agent;
        this.state.currentAgent = agent;

        const protocolType = agent.agent_type || 'a2a';
        const protocolLabel = protocolType === 'mcp' ? 'MCP' : 'A2A';

        this.render(this.navbar('my-agents') + `
        <div class="page">
            <div class="workspace">
                <div class="workspace-header">
                    <div class="agent-icon" style="background: linear-gradient(135deg, ${agent.color}, ${agent.color}88)">${agent.icon}</div>
                    <div>
                        <div style="font-size:18px; font-weight:700; display:flex; align-items:center; gap:8px">
                            ${agent.name}
                            <span class="protocol-badge ${protocolType}">${protocolLabel}</span>
                        </div>
                        <div style="font-size:13px; color:var(--text-secondary)">${agent.tagline}</div>
                    </div>
                    <button class="btn btn-secondary btn-sm" style="margin-left:auto" onclick="App.navigate('my-agents')">← Back</button>
                </div>

                <div class="workspace-input">
                    <div class="form-group" style="margin-bottom:12px">
                        <label class="form-label">Input</label>
                        <textarea class="form-input" id="ws-input" placeholder="Enter your query or topic..." rows="4"></textarea>
                    </div>
                    <button class="btn btn-primary" id="ws-run-btn" onclick="App.runAgent('${agentId}')">Run Agent</button>
                </div>

                <div class="workspace-output hidden" id="ws-output-area">
                    <h3 style="font-size:14px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-secondary); margin-bottom:16px">Output</h3>
                    <div id="ws-output" class="output-content"></div>
                </div>
            </div>
        </div>`);
        document.getElementById('ws-input').focus();
    },

    async runAgent(agentId) {
        const input = document.getElementById('ws-input').value.trim();
        if (!input) return showToast('Please enter some input', 'error');

        const btn = document.getElementById('ws-run-btn');
        btn.disabled = true;
        btn.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px;margin-right:8px"></div> Running...';

        const outputArea = document.getElementById('ws-output-area');
        const outputEl = document.getElementById('ws-output');
        outputArea.classList.remove('hidden');
        outputEl.innerHTML = '<div class="loading"><div class="spinner"></div> Agent is processing...</div>';

        const res = await API.post(`/agents/${agentId}/run`, { input });

        btn.disabled = false;
        btn.textContent = 'Run Agent';

        if (res.ok && res.data.result) {
            const r = res.data.result;
            if (r.success) {
                outputEl.innerHTML = `<div class="output-json">${this.formatOutput(r)}</div>`;
            } else {
                outputEl.innerHTML = `<div class="alert alert-error">${r.error || 'Agent returned an error.'}</div>`;
            }
        } else {
            outputEl.innerHTML = `<div class="alert alert-error">${res.data.error || 'Request failed.'}</div>`;
        }
    },


    // =========================================================================
    // PIPELINES PAGE
    // =========================================================================
    async renderPipelines() {
        this.render(this.navbar('pipelines') + `
        <div class="page">
            <div class="section-header">
                <div>
                    <h1 class="page-title">Pipelines</h1>
                    <p class="page-subtitle">Chain multiple agents into automated workflows</p>
                </div>
                <button class="btn btn-primary" onclick="App.navigate('pipeline-builder')">+ New Pipeline</button>
            </div>
            <div class="pipelines-list" id="pipelines-list">
                <div class="loading"><div class="spinner"></div> Loading...</div>
            </div>
        </div>`);

        const res = await API.get('/pipelines');
        const pipelines = res.ok ? res.data.pipelines : [];
        this.state.pipelines = pipelines;

        const list = document.getElementById('pipelines-list');
        if (!pipelines.length) {
            list.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">~</div>
                <h3>No pipelines yet</h3>
                <p>Create a pipeline to chain multiple agents together, just like N8N workflows.</p>
                <button class="btn btn-primary" style="margin-top:16px" onclick="App.navigate('pipeline-builder')">Create Pipeline</button>
            </div>`;
            return;
        }

        list.innerHTML = pipelines.map(p => {
            const config = p.config || {};
            const steps = (config.steps || []).map(s => s.label || s.agent_id).join(' → ');
            return `
            <div class="pipeline-list-item">
                <div class="pipeline-list-info">
                    <div class="pipeline-list-name">${p.name}</div>
                    <div class="pipeline-list-meta">${steps} | ${(config.steps || []).length} steps | Created ${new Date(p.created_at).toLocaleDateString()}</div>
                </div>
                <div class="pipeline-list-actions">
                    <button class="btn btn-primary btn-sm" onclick="App.navigate('pipeline-run/${p.id}')">Run</button>
                    <button class="btn btn-danger btn-sm" onclick="App.deletePipeline(${p.id})">Delete</button>
                </div>
            </div>`;
        }).join('');
    },

    async deletePipeline(id) {
        if (!confirm('Delete this pipeline?')) return;
        const res = await API.delete(`/pipelines/${id}`);
        if (res.ok) {
            showToast('Pipeline deleted', 'success');
            this.renderPipelines();
        } else {
            showToast(res.data.error, 'error');
        }
    },


    // =========================================================================
    // PIPELINE BUILDER
    // =========================================================================
    async renderPipelineBuilder() {
        // Get user's agents
        const res = await API.get('/my-agents');
        const agents = res.ok ? res.data.agents : [];
        this.state.myAgents = agents;
        this.state.pipelineSteps = [];

        this.render(this.navbar('pipelines') + `
        <div class="page">
            <div class="page-header">
                <h1 class="page-title">Pipeline Builder</h1>
                <p class="page-subtitle">Click agents from the sidebar to build your workflow</p>
            </div>

            <div class="form-group" style="max-width:500px; margin-bottom:24px">
                <label class="form-label">Pipeline Name</label>
                <input class="form-input" id="pipeline-name" type="text" placeholder="My Research Pipeline">
            </div>

            <div class="pipeline-builder">
                <div class="pipeline-sidebar">
                    <h3>Available Agents</h3>
                    ${agents.length ? agents.map(a => `
                    <div class="pipeline-agent-item" onclick="App.addPipelineStep('${a.id}', '${a.name}', '${a.color}', '${a.icon}')">
                        <div class="mini-icon" style="background:linear-gradient(135deg,${a.color},${a.color}88)">${a.icon}</div>
                        <div>
                            <div style="font-size:13px;font-weight:600">${a.name}</div>
                            <div style="font-size:11px;color:var(--text-tertiary)">${a.category}</div>
                        </div>
                    </div>`).join('')
                    : '<p style="font-size:13px;color:var(--text-tertiary)">Purchase agents from the marketplace first.</p>'}
                </div>

                <div class="pipeline-canvas">
                    <div id="pipeline-steps" class="pipeline-steps">
                        <div class="pipeline-empty" id="pipeline-empty">
                            <div class="pipeline-empty-icon">+</div>
                            <p>Click agents on the left to add them to your pipeline</p>
                        </div>
                    </div>

                    <div class="pipeline-actions">
                        <button class="btn btn-primary" onclick="App.savePipeline()">Save Pipeline</button>
                        <button class="btn btn-secondary" onclick="App.navigate('pipelines')">Cancel</button>
                    </div>
                </div>
            </div>
        </div>`);
    },

    addPipelineStep(agentId, name, color, icon) {
        this.state.pipelineSteps.push({ agent_id: agentId, label: name, color, icon });
        this.renderPipelineSteps();
    },

    removePipelineStep(index) {
        this.state.pipelineSteps.splice(index, 1);
        this.renderPipelineSteps();
    },

    renderPipelineSteps() {
        const container = document.getElementById('pipeline-steps');
        const steps = this.state.pipelineSteps;

        if (!steps.length) {
            container.innerHTML = `
            <div class="pipeline-empty" id="pipeline-empty">
                <div class="pipeline-empty-icon">+</div>
                <p>Click agents on the left to add them to your pipeline</p>
            </div>`;
            return;
        }

        let html = '';
        steps.forEach((step, i) => {
            if (i > 0) {
                html += `<div class="pipeline-connector">|</div>`;
            }
            html += `
            <div class="pipeline-step">
                <div class="step-number" style="background:${step.color}">${i + 1}</div>
                <div class="step-info">
                    <div class="step-name">${step.label}</div>
                    <div class="step-agent">${step.agent_id}</div>
                </div>
                <button class="step-remove" onclick="App.removePipelineStep(${i})">×</button>
            </div>`;
        });

        container.innerHTML = html;
    },

    async savePipeline() {
        const name = document.getElementById('pipeline-name').value.trim();
        const steps = this.state.pipelineSteps;

        if (!name) return showToast('Give your pipeline a name', 'error');
        if (!steps.length) return showToast('Add at least one agent to the pipeline', 'error');

        const config = {
            steps: steps.map(s => ({ agent_id: s.agent_id, label: s.label })),
        };

        const res = await API.post('/pipelines', { name, config });
        if (res.ok) {
            showToast('Pipeline saved!', 'success');
            this.navigate('pipelines');
        } else {
            showToast(res.data.error, 'error');
        }
    },


    // =========================================================================
    // PIPELINE RUN PAGE
    // =========================================================================
    async renderPipelineRun(pipelineId) {
        if (!pipelineId) return this.navigate('pipelines');

        const res = await API.get('/pipelines');
        const pipeline = (res.ok ? res.data.pipelines : []).find(p => p.id == pipelineId);
        if (!pipeline) { showToast('Pipeline not found', 'error'); return this.navigate('pipelines'); }

        const steps = (pipeline.config.steps || []);

        this.render(this.navbar('pipelines') + `
        <div class="page">
            <div class="workspace" style="max-width:900px">
                <div class="workspace-header">
                    <div style="flex:1">
                        <div style="font-size:18px;font-weight:700">${pipeline.name}</div>
                        <div style="font-size:13px;color:var(--text-secondary)">${steps.map(s => s.label).join(' → ')}</div>
                    </div>
                    <button class="btn btn-secondary btn-sm" onclick="App.navigate('pipelines')">← Back</button>
                </div>

                <div class="workspace-input">
                    <div class="form-group" style="margin-bottom:12px">
                        <label class="form-label">Pipeline Input</label>
                        <textarea class="form-input" id="pipe-input" placeholder="Enter the starting input for the pipeline..." rows="4"></textarea>
                    </div>
                    <button class="btn btn-primary" id="pipe-run-btn" onclick="App.executePipeline(${pipelineId})">Run Pipeline</button>
                </div>

                <div class="hidden" id="pipe-results-area">
                    <h3 style="font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-secondary);margin-bottom:16px">Pipeline Results</h3>
                    <div id="pipe-results"></div>
                </div>
            </div>
        </div>`);
        document.getElementById('pipe-input').focus();
    },

    async executePipeline(pipelineId) {
        const input = document.getElementById('pipe-input').value.trim();
        if (!input) return showToast('Enter input for the pipeline', 'error');

        const btn = document.getElementById('pipe-run-btn');
        btn.disabled = true;
        btn.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px;margin-right:8px"></div> Running Pipeline...';

        const resultsArea = document.getElementById('pipe-results-area');
        const resultsEl = document.getElementById('pipe-results');
        resultsArea.classList.remove('hidden');
        resultsEl.innerHTML = '<div class="loading"><div class="spinner"></div> Executing pipeline steps...</div>';

        const res = await API.post(`/pipelines/${pipelineId}/run`, { input });

        btn.disabled = false;
        btn.textContent = 'Run Pipeline';

        if (res.ok && res.data.results) {
            const results = res.data.results;
            const stepResults = results.step_results || [];

            let html = '';

            if (results.total_elapsed_sec) {
                html += `<div style="font-size:13px;color:var(--text-secondary);margin-bottom:16px">Pipeline completed in ${results.total_elapsed_sec}s</div>`;
            }

            stepResults.forEach((sr, i) => {
                const statusColor = sr.success ? 'var(--accent-green)' : 'var(--accent-red)';
                const statusIcon = sr.success ? '✓' : '✗';
                html += `
                <div class="step-result-card">
                    <div class="step-result-header">
                        <div class="step-result-title">
                            <span style="color:${statusColor}">${statusIcon}</span>
                            Step ${sr.step}: ${sr.label}
                        </div>
                        <span class="step-result-time">${sr.elapsed_sec}s</span>
                    </div>
                    <div class="step-result-output">
                        <div class="output-json" style="max-height:250px">${sr.success
                            ? this.syntaxHighlight(JSON.stringify(sr.output || {}, null, 2))
                            : `<span style="color:var(--accent-red)">${sr.error || 'Failed'}</span>`
                        }</div>
                    </div>
                </div>`;
            });

            if (results.error) {
                html += `<div class="alert alert-error">${results.error}</div>`;
            }

            resultsEl.innerHTML = html;
        } else {
            resultsEl.innerHTML = `<div class="alert alert-error">${res.data.error || 'Pipeline execution failed.'}</div>`;
        }
    },


    // =========================================================================
    // TOOLS PAGE — Hosted AI Tools
    // =========================================================================
    async renderTools() {
        this.render(this.navbar('tools') + `
        <div class="page">
            <div class="page-header">
                <h1 class="page-title">AI Tools</h1>
                <p class="page-subtitle">Powerful AI-powered utilities — no setup needed, just paste your text and go</p>
            </div>
            <div class="agents-grid" id="tools-grid">
                <div class="loading"><div class="spinner"></div> Loading tools...</div>
            </div>
        </div>`);

        const res = await API.get('/tools');
        const tools = res.ok ? res.data.tools : [];

        const grid = document.getElementById('tools-grid');
        if (!tools.length) {
            grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">~</div><h3>No tools available</h3></div>';
            return;
        }

        grid.innerHTML = tools.map(t => `
        <div class="agent-card tool-card" style="--card-accent: ${t.color}; cursor:pointer" onclick="App.navigate('tool-run/${t.id}')">
            <div class="agent-card-header">
                <div class="agent-icon" style="background: linear-gradient(135deg, ${t.color}, ${t.color}88); font-size:26px">${t.icon}</div>
                <div class="agent-card-info">
                    <div class="agent-card-name">
                        ${t.name}
                        <span class="protocol-badge" style="background:rgba(255,255,255,0.06);border-color:rgba(255,255,255,0.12);color:var(--text-secondary)">TOOL</span>
                    </div>
                    <div class="agent-card-tagline">${t.tagline}</div>
                </div>
            </div>
            <div class="agent-card-body">
                <p class="agent-card-desc">${t.description}</p>
            </div>
            <div class="agent-card-footer" style="border-top:1px solid var(--border-subtle); padding-top:16px">
                <div style="display:flex;align-items:center;gap:6px">
                    <span class="tag" style="border-color:${t.color}44; color:${t.color}">${t.category}</span>
                </div>
                <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); App.navigate('tool-run/${t.id}')">Use Tool →</button>
            </div>
        </div>`).join('');
    },


    // =========================================================================
    // TOOL RUNNER PAGE
    // =========================================================================
    async renderToolRunner(toolId) {
        if (!toolId) return this.navigate('tools');

        // Fetch tool info
        const res = await API.get('/tools');
        const tools = res.ok ? res.data.tools : [];
        const tool = tools.find(t => t.id === toolId);

        if (!tool) {
            showToast('Tool not found', 'error');
            return this.navigate('tools');
        }

        // Build options HTML
        let optionsHtml = '';
        if (tool.options && tool.options.length) {
            optionsHtml = tool.options.map(opt => {
                if (opt.type === 'select') {
                    const choices = opt.choices.map(c => 
                        `<option value="${c}" ${c === opt.default ? 'selected' : ''}>${c.charAt(0).toUpperCase() + c.slice(1)}</option>`
                    ).join('');
                    return `
                    <div class="form-group" style="margin-bottom:12px">
                        <label class="form-label">${opt.label}</label>
                        <select class="form-input" id="tool-opt-${opt.id}" style="cursor:pointer">
                            ${choices}
                        </select>
                    </div>`;
                }
                return '';
            }).join('');
        }

        this.render(this.navbar('tools') + `
        <div class="page">
            <div class="workspace" style="max-width:900px">
                <div class="workspace-header">
                    <div class="agent-icon" style="background: linear-gradient(135deg, ${tool.color}, ${tool.color}88); font-size:24px">${tool.icon}</div>
                    <div style="flex:1">
                        <div style="font-size:18px; font-weight:700; display:flex; align-items:center; gap:8px">
                            ${tool.name}
                            <span class="protocol-badge" style="background:rgba(255,255,255,0.06);border-color:rgba(255,255,255,0.12);color:var(--text-secondary)">TOOL</span>
                        </div>
                        <div style="font-size:13px; color:var(--text-secondary)">${tool.tagline}</div>
                    </div>
                    <button class="btn btn-secondary btn-sm" onclick="App.navigate('tools')">← Back</button>
                </div>

                <div class="workspace-input">
                    ${optionsHtml}
                    <div class="form-group" style="margin-bottom:12px">
                        <label class="form-label">Input</label>
                        <textarea class="form-input" id="tool-input" placeholder="${tool.input_placeholder || 'Enter your text here...'}" rows="6"></textarea>
                    </div>
                    <div style="display:flex;align-items:center;gap:12px">
                        <button class="btn btn-primary" id="tool-run-btn" onclick="App.executeTool('${tool.id}')">Run ${tool.name}</button>
                        <span style="font-size:12px;color:var(--text-tertiary)" id="tool-char-count">0 characters</span>
                    </div>
                </div>

                <div class="workspace-output hidden" id="tool-output-area">
                    <h3 style="font-size:14px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-secondary); margin-bottom:16px">Result</h3>
                    <div id="tool-output" class="output-content"></div>
                </div>
            </div>
        </div>`);

        // Character count
        const inputEl = document.getElementById('tool-input');
        const countEl = document.getElementById('tool-char-count');
        inputEl.focus();
        inputEl.addEventListener('input', () => {
            const len = inputEl.value.length;
            countEl.textContent = `${len.toLocaleString()} characters`;
            countEl.style.color = len > 8000 ? 'var(--accent-red)' : 'var(--text-tertiary)';
        });
    },

    async executeTool(toolId) {
        const inputEl = document.getElementById('tool-input');
        const input = inputEl.value.trim();
        if (!input) return showToast('Please enter some text', 'error');

        const btn = document.getElementById('tool-run-btn');
        btn.disabled = true;
        btn.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px;margin-right:8px"></div> Processing...';

        const outputArea = document.getElementById('tool-output-area');
        const outputEl = document.getElementById('tool-output');
        outputArea.classList.remove('hidden');
        outputEl.innerHTML = '<div class="loading"><div class="spinner"></div> AI is processing your text...</div>';

        // Gather options
        const options = {};
        document.querySelectorAll('[id^="tool-opt-"]').forEach(el => {
            const key = el.id.replace('tool-opt-', '');
            options[key] = el.value;
        });

        const res = await API.post(`/tools/${toolId}/run`, { input, options });

        btn.disabled = false;
        btn.textContent = `Run Again`;

        if (res.ok && res.data.result) {
            const r = res.data.result;
            outputEl.innerHTML = this.renderToolResult(toolId, r);
        } else {
            outputEl.innerHTML = `<div class="alert alert-error">${res.data.error || 'Tool execution failed.'}</div>`;
        }
    },

    renderToolResult(toolId, result) {
        const time = result.processing_time ? `<div style="font-size:12px;color:var(--text-tertiary);margin-bottom:12px">Processed in ${result.processing_time}s</div>` : '';

        if (toolId === 'summarizer') {
            const keyPoints = (result.key_points || []).map(p => `<li>${this.escapeHtml(p)}</li>`).join('');
            const stats = result.stats || {};
            return `
            ${time}
            <div class="tool-result-section">
                <div class="tool-result-label">Summary</div>
                <div class="tool-result-text">${this.escapeHtml(result.summary || '')}</div>
            </div>
            ${keyPoints ? `
            <div class="tool-result-section">
                <div class="tool-result-label">Key Points</div>
                <ul class="tool-result-list">${keyPoints}</ul>
            </div>` : ''}
            <div class="tool-result-stats">
                <div class="tool-stat"><span class="tool-stat-value">${stats.original_words || '?'}</span><span class="tool-stat-label">Original Words</span></div>
                <div class="tool-stat"><span class="tool-stat-value">${stats.summary_words || '?'}</span><span class="tool-stat-label">Summary Words</span></div>
                <div class="tool-stat"><span class="tool-stat-value">${stats.compression_ratio || '?'}%</span><span class="tool-stat-label">Compression</span></div>
            </div>`;
        }

        if (toolId === 'extractor') {
            const entities = result.entities || {};
            const renderList = (items, color) => items.length
                ? items.map(i => `<span class="entity-chip" style="border-color:${color}44;color:${color}">${this.escapeHtml(i)}</span>`).join('')
                : '<span style="color:var(--text-tertiary);font-size:12px">None found</span>';

            const keywords = (result.keywords || []).map(k => `<span class="tag">${this.escapeHtml(k)}</span>`).join('');
            const topics = (result.topics || []).map(t => `<span class="tag" style="border-color:var(--accent-purple);color:var(--accent-purple)">${this.escapeHtml(t)}</span>`).join('');
            const stats = result.stats || {};

            return `
            ${time}
            <div class="tool-result-section">
                <div class="tool-result-label">Category: <span style="color:var(--accent-cyan)">${this.escapeHtml(result.category || 'Unknown')}</span> · Language: <span style="color:var(--accent-green)">${this.escapeHtml(result.language || 'Unknown')}</span></div>
            </div>
            <div class="tool-result-section">
                <div class="tool-result-label">👤 People</div>
                <div class="entity-chips">${renderList(entities.people || [], '#00d4ff')}</div>
            </div>
            <div class="tool-result-section">
                <div class="tool-result-label">🏢 Organizations</div>
                <div class="entity-chips">${renderList(entities.organizations || [], '#a855f7')}</div>
            </div>
            <div class="tool-result-section">
                <div class="tool-result-label">📍 Locations</div>
                <div class="entity-chips">${renderList(entities.locations || [], '#00ff88')}</div>
            </div>
            <div class="tool-result-section">
                <div class="tool-result-label">📅 Dates</div>
                <div class="entity-chips">${renderList(entities.dates || [], '#ff9500')}</div>
            </div>
            <div class="tool-result-section">
                <div class="tool-result-label">🔑 Keywords</div>
                <div style="display:flex;flex-wrap:wrap;gap:6px">${keywords || '<span style="color:var(--text-tertiary);font-size:12px">None</span>'}</div>
            </div>
            <div class="tool-result-section">
                <div class="tool-result-label">📂 Topics</div>
                <div style="display:flex;flex-wrap:wrap;gap:6px">${topics || '<span style="color:var(--text-tertiary);font-size:12px">None</span>'}</div>
            </div>
            <div class="tool-result-stats">
                <div class="tool-stat"><span class="tool-stat-value">${stats.total_entities || 0}</span><span class="tool-stat-label">Entities</span></div>
                <div class="tool-stat"><span class="tool-stat-value">${stats.total_keywords || 0}</span><span class="tool-stat-label">Keywords</span></div>
            </div>`;
        }

        if (toolId === 'rewriter') {
            const changes = (result.changes_made || []).map(c => `<li>${this.escapeHtml(c)}</li>`).join('');
            const stats = result.stats || {};
            return `
            ${time}
            <div class="tool-result-section">
                <div class="tool-result-label">Rewritten Text <span class="protocol-badge" style="background:rgba(0,255,136,0.1);border-color:rgba(0,255,136,0.2);color:var(--accent-green);font-size:10px;margin-left:8px">${this.escapeHtml(result.tone || 'N/A')} tone</span></div>
                <div class="tool-result-text" style="white-space:pre-wrap">${this.escapeHtml(result.rewritten_text || '')}</div>
                <button class="btn btn-secondary btn-sm" style="margin-top:12px" onclick="App.copyText(document.querySelector('.tool-result-text').textContent)">Copy Rewritten Text</button>
            </div>
            ${changes ? `
            <div class="tool-result-section">
                <div class="tool-result-label">Changes Made</div>
                <ul class="tool-result-list">${changes}</ul>
            </div>` : ''}
            <div class="tool-result-stats">
                <div class="tool-stat"><span class="tool-stat-value">${stats.original_words || '?'}</span><span class="tool-stat-label">Original Words</span></div>
                <div class="tool-stat"><span class="tool-stat-value">${stats.rewritten_words || '?'}</span><span class="tool-stat-label">Rewritten Words</span></div>
            </div>`;
        }

        // Fallback: raw JSON
        return `${time}<div class="output-json">${this.syntaxHighlight(JSON.stringify(result, null, 2))}</div>`;
    },
};


// Boot the app
App.init();
