/* ============================================================
   AI Agent Marketplace -- Frontend Application
   ============================================================
   Single-page application with hash-based routing.
   Pages: Auth, Marketplace, My Agents, Workspace, Pipelines
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
                <p class="page-subtitle">Discover and purchase powerful AI agents</p>
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
            return `
            <div class="agent-card" style="--card-accent: ${a.color}">
                <div class="agent-card-header">
                    <div class="agent-icon" style="background: linear-gradient(135deg, ${a.color}, ${a.color}88)">${a.icon}</div>
                    <div class="agent-card-info">
                        <div class="agent-card-name">${a.name}</div>
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
                        ? `<span class="owned-badge">Owned</span>`
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
    // MY AGENTS PAGE
    // =========================================================================
    async renderMyAgents() {
        this.render(this.navbar('my-agents') + `
        <div class="page">
            <div class="page-header">
                <h1 class="page-title">My Agents</h1>
                <p class="page-subtitle">Your purchased agents -- use them directly or integrate via Agent Card</p>
            </div>
            <div id="my-agents-grid" style="display:flex;flex-direction:column;gap:24px">
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

        grid.innerHTML = agents.map(a => `
        <div class="agent-card" style="--card-accent: ${a.color}">
            <div class="agent-card-header">
                <div class="agent-icon" style="background: linear-gradient(135deg, ${a.color}, ${a.color}88)">${a.icon}</div>
                <div class="agent-card-info">
                    <div class="agent-card-name">${a.name}</div>
                    <div class="agent-card-tagline">${a.tagline}</div>
                </div>
            </div>

            <!-- Agent Card & Connection Info (only visible to purchasers) -->
            <div style="margin:16px 0;padding:16px;background:var(--bg-secondary);border:1px solid var(--border-subtle);border-radius:var(--radius-sm)">
                <div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-tertiary);margin-bottom:10px">Integration Details</div>

                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                    <span style="font-size:12px;color:var(--text-secondary);min-width:85px;font-weight:600">A2A Server</span>
                    <code style="flex:1;font-size:12px;padding:6px 10px;background:var(--bg-primary);border:1px solid var(--border-subtle);border-radius:6px;color:var(--accent-cyan);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${a.a2a_url || 'N/A'}</code>
                    <button class="btn btn-secondary btn-sm" style="padding:4px 10px;font-size:11px" onclick="App.copyText('${a.a2a_url}')">Copy</button>
                </div>

                <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
                    <span style="font-size:12px;color:var(--text-secondary);min-width:85px;font-weight:600">Agent Card</span>
                    <code style="flex:1;font-size:12px;padding:6px 10px;background:var(--bg-primary);border:1px solid var(--border-subtle);border-radius:6px;color:var(--accent-purple);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${a.agent_card_url || 'N/A'}</code>
                    <button class="btn btn-secondary btn-sm" style="padding:4px 10px;font-size:11px" onclick="App.copyText('${a.agent_card_url}')">Copy</button>
                </div>

                <button class="btn btn-secondary btn-sm" style="width:100%" onclick="App.viewAgentCard('${a.id}')">View Full Agent Card JSON</button>
            </div>

            <div class="agent-card-footer" style="border-top:none; padding-top:0">
                <div class="agent-status">
                    <span class="status-dot ${a.online ? 'online' : 'offline'}"></span>
                    ${a.online ? 'Online' : 'Offline'}
                </div>
                <button class="btn btn-primary btn-sm" onclick="App.navigate('workspace/${a.id}')" ${!a.online ? 'disabled' : ''}>
                    Use Agent
                </button>
            </div>

            <!-- Agent Card JSON viewer (initially hidden) -->
            <div id="card-viewer-${a.id}" class="hidden" style="margin-top:12px"></div>
        </div>`).join('');
    },

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

    async viewAgentCard(agentId) {
        const viewer = document.getElementById(`card-viewer-${agentId}`);
        if (!viewer) return;

        // Toggle: if already visible, hide it
        if (!viewer.classList.contains('hidden')) {
            viewer.classList.add('hidden');
            return;
        }

        viewer.classList.remove('hidden');
        viewer.innerHTML = '<div class="loading" style="padding:16px"><div class="spinner"></div> Fetching Agent Card...</div>';

        const res = await API.get(`/agents/${agentId}/card`);

        if (res.ok && res.data.agent_card) {
            const card = res.data.agent_card;
            viewer.innerHTML = `
            <div style="background:var(--bg-secondary);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);overflow:hidden">
                <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid var(--border-subtle)">
                    <span style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-tertiary)">Agent Card JSON</span>
                    <button class="btn btn-secondary btn-sm" style="padding:3px 10px;font-size:11px" onclick="App.copyText(JSON.stringify(${JSON.stringify(card).replace(/'/g, "\\'")}, null, 2))">Copy JSON</button>
                </div>
                <div class="output-json" style="max-height:350px;margin:0;border-radius:0">${this.syntaxHighlight(JSON.stringify(card, null, 2))}</div>
            </div>`;
        } else {
            viewer.innerHTML = `<div class="alert alert-error" style="margin:0">${res.data.error || 'Failed to fetch Agent Card.'}</div>`;
        }
    },


    // =========================================================================
    // WORKSPACE PAGE -- Use a single agent
    // =========================================================================
    async renderWorkspace(agentId) {
        if (!agentId) return this.navigate('my-agents');

        // Get agent info
        const res = await API.get(`/marketplace/${agentId}`);
        if (!res.ok) { showToast('Agent not found', 'error'); return this.navigate('my-agents'); }
        const agent = res.data.agent;
        this.state.currentAgent = agent;

        this.render(this.navbar('my-agents') + `
        <div class="page">
            <div class="workspace">
                <div class="workspace-header">
                    <div class="agent-icon" style="background: linear-gradient(135deg, ${agent.color}, ${agent.color}88)">${agent.icon}</div>
                    <div>
                        <div style="font-size:18px; font-weight:700">${agent.name}</div>
                        <div style="font-size:13px; color:var(--text-secondary)">${agent.tagline}</div>
                    </div>
                    <button class="btn btn-secondary btn-sm" style="margin-left:auto" onclick="App.navigate('my-agents')">Back</button>
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

    formatOutput(data) {
        // Clean display of agent output
        const clean = { ...data };
        delete clean.success;
        delete clean.elapsed_sec;

        const elapsed = data.elapsed_sec ? `<div style="color:var(--text-tertiary);font-size:12px;margin-bottom:8px">Completed in ${data.elapsed_sec}s</div>` : '';
        return elapsed + this.syntaxHighlight(JSON.stringify(clean, null, 2));
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
            const steps = (config.steps || []).map(s => s.label || s.agent_id).join(' -> ');
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
                <p class="page-subtitle">Drag agents from the sidebar to build your workflow</p>
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
                <button class="step-remove" onclick="App.removePipelineStep(${i})">x</button>
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
                        <div style="font-size:13px;color:var(--text-secondary)">${steps.map(s => s.label).join(' -> ')}</div>
                    </div>
                    <button class="btn btn-secondary btn-sm" onclick="App.navigate('pipelines')">Back</button>
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
                const statusIcon = sr.success ? '[OK]' : '[FAIL]';
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
};


// Boot the app
App.init();
