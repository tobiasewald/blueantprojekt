// Blue Ant KI Portfolio-Dashboard - Frontend-Logik (Deutsche Version)

document.addEventListener('DOMContentLoaded', () => {
    // Statusverwaltung
    let currentPortfolioData = null;
    let statusChartInstance = null;
    let effortChartInstance = null;

    // Toast-Benachrichtigungssystem
    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        let iconClass = 'fa-info-circle';
        if (type === 'success') iconClass = 'fa-circle-check';
        if (type === 'error') iconClass = 'fa-triangle-exclamation';
        if (type === 'warning') iconClass = 'fa-circle-exclamation';

        toast.innerHTML = `
            <i class="fa-solid ${iconClass}"></i>
            <span>${message}</span>
        `;
        
        container.appendChild(toast);

        // Toast nach Ablauf der Animation entfernen
        setTimeout(() => {
            toast.style.animation = 'toast-in 0.3s ease reverse forwards';
            toast.addEventListener('animationend', () => {
                toast.remove();
            });
        }, 4000);
    }

    // Hilfsfunktion: Headers mit Autorisierungstoken
    function getApiHeaders() {
        const token = localStorage.getItem('blueant_token') || '';
        const ollamaToken = localStorage.getItem('ollama_token') || '';
        const headers = {
            'Content-Type': 'application/json'
        };
        if (token) {
            headers['X-Blueant-API-Key'] = token;
        }
        if (ollamaToken) {
            headers['X-Ollama-API-Key'] = ollamaToken;
        }
        return headers;
    }

    // Modal-Steuerung: Autorisierungstoken
    const keyModal = document.getElementById('key-modal');
    const setKeyBtn = document.getElementById('set-key-btn');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const saveTokenBtn = document.getElementById('save-token-btn');
    const clearTokenBtn = document.getElementById('clear-token-btn');
    const modalApiTokenInput = document.getElementById('modal-api-token');
    const modalOllamaTokenInput = document.getElementById('modal-ollama-token');

    function updateTokenButtonState() {
        const token = localStorage.getItem('blueant_token');
        const ollamaToken = localStorage.getItem('ollama_token');
        if (token) {
            setKeyBtn.innerHTML = `<i class="fa-solid fa-key-skeleton text-green"></i> Token konfiguriert${ollamaToken ? ' + Ollama' : ''}`;
            setKeyBtn.classList.add('token-configured');
        } else {
            setKeyBtn.innerHTML = '<i class="fa-solid fa-key"></i> API-Schlüssel festlegen';
            setKeyBtn.classList.remove('token-configured');
        }
    }

    setKeyBtn.addEventListener('click', () => {
        const token = localStorage.getItem('blueant_token') || '';
        const ollamaToken = localStorage.getItem('ollama_token') || '';
        modalApiTokenInput.value = token;
        modalOllamaTokenInput.value = ollamaToken;
        keyModal.classList.remove('hidden');
    });

    closeModalBtn.addEventListener('click', () => {
        keyModal.classList.add('hidden');
    });

    saveTokenBtn.addEventListener('click', () => {
        const token = modalApiTokenInput.value.trim();
        const ollamaToken = modalOllamaTokenInput.value.trim();
        if (token) {
            localStorage.setItem('blueant_token', token);
            if (ollamaToken) {
                localStorage.setItem('ollama_token', ollamaToken);
            } else {
                localStorage.removeItem('ollama_token');
            }
            showToast('Schlüssel lokal gespeichert.', 'success');
            updateTokenButtonState();
            keyModal.classList.add('hidden');
            loadPortfolios(); // Portfolios mit neuem Token laden
        } else {
            showToast('Bitte geben Sie einen gültigen Blue Ant REST API-Token ein.', 'warning');
        }
    });

    clearTokenBtn.addEventListener('click', () => {
        localStorage.removeItem('blueant_token');
        localStorage.removeItem('ollama_token');
        modalApiTokenInput.value = '';
        modalOllamaTokenInput.value = '';
        showToast('Schlüssel gelöscht.', 'info');
        updateTokenButtonState();
        keyModal.classList.add('hidden');
    });

    // Modal schließen bei Klick außerhalb des Modal-Inhalts
    window.addEventListener('click', (e) => {
        if (e.target === keyModal) {
            keyModal.classList.add('hidden');
        }
    });

    // Navigation & Tab-Wechsel
    const navItems = document.querySelectorAll('.nav-item');
    const tabContents = document.querySelectorAll('.tab-content');
    const pageTitle = document.getElementById('page-title');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Aktive Klassen entfernen
            navItems.forEach(nav => nav.classList.remove('active'));
            tabContents.forEach(tab => tab.classList.remove('active'));

            // Aktive Klasse für das geklickte Element setzen
            item.classList.add('active');
            
            // Entsprechenden Tab anzeigen
            const targetId = item.getAttribute('data-target');
            const targetTab = document.getElementById(targetId);
            if (targetTab) {
                targetTab.classList.add('active');
            }

            // Titel anpassen
            const tabName = item.textContent.trim();
            pageTitle.textContent = tabName;

            // Spezifische Aktionen beim Öffnen eines Tabs
            if (targetId === 'prompts-section') {
                loadPrompts();
            } else if (targetId === 'settings-section') {
                loadSettings();
            }
        });
    });

    // Lade-Overlay umschalten
    const loadingOverlay = document.getElementById('loading-overlay');
    function showLoading(show = true) {
        if (show) {
            loadingOverlay.classList.remove('hidden');
        } else {
            loadingOverlay.classList.add('hidden');
        }
    }

    // Portfolios in Dropdown laden
    const portfolioSelect = document.getElementById('portfolio-select');
    
    async function loadPortfolios() {
        try {
            const res = await fetch('/api/portfolios', {
                headers: getApiHeaders()
            });

            if (res.status === 401) {
                showToast('Autorisierungstoken fehlt oder ist ungültig. Bitte konfigurieren Sie das Token.', 'warning');
                keyModal.classList.remove('hidden');
                return;
            }

            if (!res.ok) {
                throw new Error(`Fehler beim Laden der Portfolios: ${res.statusText}`);
            }

            const data = await res.json();
            const portfolios = data.portfolios || [];
            
            // Dropdown zurücksetzen
            portfolioSelect.innerHTML = '<option value="">-- Portfolio auswählen --</option>';
            
            portfolios.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = `${p.name} (${p.number || p.id})`;
                portfolioSelect.appendChild(opt);
            });

            if (portfolios.length > 0) {
                showToast('Portfolios erfolgreich geladen.', 'success');
            }
        } catch (err) {
            console.error(err);
            showToast('Portfolios konnten nicht geladen werden. Prüfen Sie Verbindung und Token.', 'error');
        }
    }

    // KI-Portfolio-Analyse starten
    const analyzeBtn = document.getElementById('analyze-btn');
    analyzeBtn.addEventListener('click', async () => {
        const portfolioId = portfolioSelect.value;
        if (!portfolioId) {
            showToast('Bitte wählen Sie zuerst ein Portfolio aus.', 'warning');
            return;
        }

        showLoading(true);
        try {
            const res = await fetch(`/api/portfolio/${portfolioId}/analysis`, {
                headers: getApiHeaders()
            });

            if (res.status === 401) {
                showLoading(false);
                showToast('Autorisierungstoken erforderlich.', 'warning');
                keyModal.classList.remove('hidden');
                return;
            }

            if (!res.ok) {
                const errorData = await res.json();
                throw new Error(errorData.detail || `Server meldete Fehler-Status: ${res.status}`);
            }

            const analysisData = await res.json();
            currentPortfolioData = analysisData;
            
            // Dashboard rendern
            renderDashboard(analysisData);
            showToast('KI-Analyse erfolgreich abgeschlossen.', 'success');
        } catch (err) {
            console.error(err);
            showToast(`Analyse fehlgeschlagen: ${err.message}`, 'error');
        } finally {
            showLoading(false);
        }
    });

    // Dashboard-Widgets mit Daten befüllen
    function renderDashboard(data) {
        const metrics = data.metrics || {};
        
        // Stats-Zähler aktualisieren
        document.getElementById('stat-total-projects').textContent = metrics.total_projects || 0;
        document.getElementById('stat-critical-projects').textContent = metrics.critical_projects_count || 0;
        
        const dist = metrics.status_distribution || { green: 0, yellow: 0, red: 0 };
        document.getElementById('stat-green-projects').textContent = dist.green || 0;
        document.getElementById('stat-yellow-projects').textContent = dist.yellow || 0;

        // Kritisches Card blinken lassen, falls kritische Projekte vorhanden sind
        const criticalCard = document.getElementById('critical-projects-card');
        if (metrics.critical_projects_count > 0) {
            criticalCard.classList.add('alert-active');
        } else {
            criticalCard.classList.remove('alert-active');
        }

        // KI Portfolio-Zusammenfassung rendern
        const summaryTextEl = document.getElementById('portfolio-ai-summary');
        summaryTextEl.textContent = data.executive_summary || '';

        // Statusampel Doughnut Chart rendern
        renderStatusChart(dist);

        // Plan- vs. Ist-Aufwand Bar Chart rendern
        const projects = data.projects_analysis || [];
        renderEffortChart(projects);

        // Tabelle befüllen
        renderProjectsTable(projects);
    }

    // Chart.js: Statusampel Doughnut Chart
    function renderStatusChart(distribution) {
        const ctx = document.getElementById('status-chart').getContext('2d');
        
        if (statusChartInstance) {
            statusChartInstance.destroy();
        }

        statusChartInstance = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Grün', 'Gelb', 'Rot'],
                datasets: [{
                    data: [distribution.green || 0, distribution.yellow || 0, distribution.red || 0],
                    backgroundColor: [
                        '#10b981', // grün
                        '#f59e0b', // gelb
                        '#ef4444'  // rot
                    ],
                    borderColor: 'rgba(255, 255, 255, 0.05)',
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#94a3b8',
                            font: { family: 'Outfit', size: 12 }
                        }
                    }
                },
                cutout: '65%'
            }
        });
    }

    // Chart.js: Plan- vs. Ist-Aufwand pro Projekt
    function renderEffortChart(projects) {
        const ctx = document.getElementById('effort-chart').getContext('2d');
        
        if (effortChartInstance) {
            effortChartInstance.destroy();
        }

        const labels = projects.map(p => p.project_name || `Projekt ${p.project_id}`);
        const plannedData = projects.map(p => p.effort_analysis?.planned_hours || 0);
        const actualData = projects.map(p => p.effort_analysis?.actual_hours || 0);

        effortChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Geplanter Aufwand (Stunden)',
                        data: plannedData,
                        backgroundColor: 'rgba(37, 99, 235, 0.4)',
                        borderColor: '#2563eb',
                        borderWidth: 1,
                        borderRadius: 4
                    },
                    {
                        label: 'Ist-Aufwand (Stunden)',
                        data: actualData,
                        backgroundColor: 'rgba(14, 165, 233, 0.4)',
                        borderColor: '#0ea5e9',
                        borderWidth: 1,
                        borderRadius: 4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            color: '#94a3b8',
                            font: { family: 'Outfit', size: 12 }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            color: '#94a3b8',
                            font: { family: 'Outfit', size: 11 }
                        }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            color: '#94a3b8',
                            font: { family: 'Outfit', size: 11 }
                        }
                    }
                }
            }
        });
    }

    // Projekt-Tabelle befüllen
    const projectsTableTbody = document.querySelector('#projects-table tbody');

    function renderProjectsTable(projects) {
        projectsTableTbody.innerHTML = '';

        if (projects.length === 0) {
            projectsTableTbody.innerHTML = `
                <tr class="placeholder-row">
                    <td colspan="8">Keine Projekte in diesem Portfolio vorhanden.</td>
                </tr>
            `;
            return;
        }

        projects.forEach(p => {
            const tr = document.createElement('tr');
            tr.dataset.projectId = p.project_id;
            
            // Statusampel HTML aufbauen
            const lightColor = (p.risk_assessment?.statusampel || 'green').toLowerCase();
            let deColor = 'Grün';
            if (lightColor === 'yellow') deColor = 'Gelb';
            if (lightColor === 'red') deColor = 'Rot';

            const lightClass = `dot-${lightColor}`;
            const trafficLightHtml = `
                <span class="traffic-indicator">
                    <span class="indicator-dot ${lightClass}"></span>
                    ${deColor}
                </span>
            `;

            // Kennzahlen
            const plan = p.effort_analysis?.planned_hours || 0;
            const ist = p.effort_analysis?.actual_hours || 0;
            const variance = p.effort_analysis?.variance_hours || 0;
            const variancePct = p.effort_analysis?.variance_percent || 0;
            const progress = p.progress_analysis?.progress_percent || 0;

            // Abweichungs-Farbe
            let varianceClass = '';
            if (variancePct > 15) varianceClass = 'text-red';
            else if (variancePct > 5) varianceClass = 'text-yellow';
            else if (variancePct < 0) varianceClass = 'text-green';

            // Kritikalität
            const isCritical = p.risk_assessment?.is_critical || false;
            const criticalityHtml = isCritical 
                ? '<span class="criticality-pill criticality-high">Kritisch</span>' 
                : '<span class="criticality-pill criticality-low">Stabil</span>';

            tr.innerHTML = `
                <td>#${p.project_id}</td>
                <td><strong>${p.project_name || 'N/A'}</strong></td>
                <td>${trafficLightHtml}</td>
                <td>${plan.toLocaleString()} h</td>
                <td>${ist.toLocaleString()} h</td>
                <td class="${varianceClass}">${variance > 0 ? '+' : ''}${variance.toLocaleString()} h (${variancePct}%)</td>
                <td>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="font-weight:600;">${progress}%</span>
                        <div style="flex-grow:1; width:60px; height:6px; background:rgba(255,255,255,0.08); border-radius:3px; overflow:hidden;">
                            <div style="width:${progress}%; height:100%; background:var(--primary);"></div>
                        </div>
                    </div>
                </td>
                <td>${criticalityHtml}</td>
            `;

            // Detail-Modal bei Zeilenklick öffnen
            tr.addEventListener('click', () => {
                showProjectDetailsModal(p);
            });

            projectsTableTbody.appendChild(tr);
        });
    }

    // Modal-Steuerung: Projekt-Detail-Bewertung
    const projectDetailModal = document.getElementById('project-detail-modal');
    const closeProjectModalBtn = document.getElementById('close-project-modal-btn');
    const projectDetailModalBody = document.getElementById('project-detail-modal-body');

    closeProjectModalBtn.addEventListener('click', () => {
        projectDetailModal.classList.add('hidden');
    });

    window.addEventListener('click', (e) => {
        if (e.target === projectDetailModal) {
            projectDetailModal.classList.add('hidden');
        }
    });

    function showProjectDetailsModal(project) {
        const effort = project.effort_analysis || {};
        const progress = project.progress_analysis || {};
        const predictions = project.predictions || {};
        const summaries = project.text_summaries || {};
        const risk = project.risk_assessment || {};

        // Kritikalitätsklasse formatieren
        const critLevel = (risk.criticality_level || 'low').toLowerCase();
        let deCritLevel = 'Niedrig';
        let critPillClass = 'criticality-low';
        
        if (critLevel === 'medium') {
            deCritLevel = 'Mittel';
            critPillClass = 'criticality-medium';
        } else if (critLevel === 'high') {
            deCritLevel = 'Hoch';
            critPillClass = 'criticality-high';
        }

        // Kritikalitätsgründe aufbauen
        const reasons = risk.criticality_reasons || [];
        let reasonsHtml = '<p>Keine kritischen Warnsignale identifiziert.</p>';
        if (reasons.length > 0) {
            reasonsHtml = `
                <ul class="reasons-list">
                    ${reasons.map(r => `<li><i class="fa-solid fa-circle-exclamation text-yellow"></i> ${r}</li>`).join('')}
                </ul>
            `;
        }

        // Projekt-Statusampel
        const lightColor = (risk.statusampel || 'green').toLowerCase();
        let deColor = 'Grün';
        if (lightColor === 'yellow') deColor = 'Gelb';
        if (lightColor === 'red') deColor = 'Rot';
        const lightDotClass = `dot-${lightColor}`;

        projectDetailModalBody.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-bottom:1px solid var(--card-border); padding-bottom:12px;">
                <div>
                    <h2 style="font-size:22px; font-weight:700;">${project.project_name}</h2>
                    <span style="color:var(--text-secondary); font-size:13px;">Projekt-Referenz-ID: #${project.project_id}</span>
                </div>
                <div style="display:flex; gap:12px; align-items:center;">
                    <span class="traffic-indicator">
                        <span class="indicator-dot ${lightDotClass}"></span>
                        Statusampel: ${deColor}
                    </span>
                    <span class="criticality-pill ${critPillClass}">KI-Kritikalität: ${deCritLevel}</span>
                </div>
            </div>

            <div class="project-ai-grid">
                <!-- Aufwands-Kennzahlen -->
                <div class="ai-details-card">
                    <h4><i class="fa-solid fa-chart-pie"></i> Plan- vs. Ist-Aufwand</h4>
                    <div class="metric-details-row">
                        <span class="metric-details-label">Geplanter Aufwand</span>
                        <span class="metric-details-val">${(effort.planned_hours || 0).toLocaleString()} Stunden</span>
                    </div>
                    <div class="metric-details-row">
                        <span class="metric-details-label">Ist-Aufwand (bisher)</span>
                        <span class="metric-details-val">${(effort.actual_hours || 0).toLocaleString()} Stunden</span>
                    </div>
                    <div class="metric-details-row">
                        <span class="metric-details-label">Abweichung</span>
                        <span class="metric-details-val ${(effort.variance_percent || 0) > 15 ? 'text-red' : ''}">
                            ${(effort.variance_hours || 0) > 0 ? '+' : ''}${(effort.variance_hours || 0).toLocaleString()} Stunden (${effort.variance_percent || 0}%)
                        </span>
                    </div>
                    <p style="margin-top:12px; font-size:13px; font-style:italic;">${effort.assessment || ''}</p>
                </div>

                <!-- Zeitplan & Fortschritt -->
                <div class="ai-details-card">
                    <h4><i class="fa-solid fa-clock-rotate-left"></i> Zeitplan & Fortschritt</h4>
                    <div class="metric-details-row">
                        <span class="metric-details-label">Gemeldeter Projektfortschritt</span>
                        <span class="metric-details-val">${progress.progress_percent || 0}%</span>
                    </div>
                    <div class="metric-details-row">
                        <span class="metric-details-label">Verstrichene Zeit (Soll)</span>
                        <span class="metric-details-val">${progress.elapsed_time_percent || 0}%</span>
                    </div>
                    <div class="metric-details-row">
                        <span class="metric-details-label">Zeitplan-Status</span>
                        <span class="metric-details-val">${progress.status_relative_to_deadline || 'N/A'}</span>
                    </div>
                </div>

                <!-- AI Prognose -->
                <div class="ai-details-card span-all">
                    <h4><i class="fa-solid fa-compass-drafting"></i> KI-Aufwands- & Zeitplanprognose</h4>
                    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:16px; margin-bottom:12px;">
                        <div class="metric-details-row" style="flex-direction:column; align-items:flex-start; border-bottom:none;">
                            <span class="metric-details-label">Verbleibende Aufwandsprognose</span>
                            <span class="metric-details-val" style="font-size:16px; margin-top:4px;">${(predictions.estimated_remaining_hours || 0).toLocaleString()} Stunden</span>
                        </div>
                        <div class="metric-details-row" style="flex-direction:column; align-items:flex-start; border-bottom:none;">
                            <span class="metric-details-label">Erwarteter Gesamtaufwand</span>
                            <span class="metric-details-val" style="font-size:16px; margin-top:4px;">${(predictions.forecasted_total_hours || 0).toLocaleString()} Stunden</span>
                        </div>
                        <div class="metric-details-row" style="flex-direction:column; align-items:flex-start; border-bottom:none;">
                            <span class="metric-details-label">Erwarteter Fertigstellungstermin</span>
                            <span class="metric-details-val" style="font-size:16px; margin-top:4px; color:var(--primary);">${predictions.expected_completion_date || 'N/A'}</span>
                        </div>
                    </div>
                    <div style="padding-top:10px; border-top:1px solid var(--card-border);">
                        <p style="font-size:14px; margin-bottom:4px;"><strong>Trendprognose:</strong> ${predictions.prognosis_text || ''}</p>
                        <span class="badge badge-purple" style="display:inline-block; margin-top:6px;">Konfidenzniveau: ${predictions.prognosis_confidence || 'mittel'}</span>
                    </div>
                </div>

                <!-- Risikobewertung -->
                <div class="ai-details-card span-all">
                    <h4><i class="fa-solid fa-triangle-exclamation"></i> Risiken & Einhaltung der Projektziele</h4>
                    <p style="margin-bottom:8px;"><strong>Projektziel-Konformität:</strong> ${risk.goals_vs_status_eval || 'Keine Konformitätskonflikte identifiziert.'}</p>
                    <p><strong>Warnsignale:</strong></p>
                    ${reasonsHtml}
                </div>

                <!-- Text-Memos -->
                <div class="ai-details-card span-all">
                    <h4><i class="fa-solid fa-comment-dots"></i> Zusammenfassung der Projektnotizen (Memos)</h4>
                    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:16px;">
                        <div>
                            <span class="metric-details-label" style="font-weight:600; display:block; margin-bottom:6px;">Status-Notiz</span>
                            <p style="font-size:13.5px;">${summaries.status_summary || 'Keine Notizen.'}</p>
                        </div>
                        <div>
                            <span class="metric-details-label" style="font-weight:600; display:block; margin-bottom:6px;">Gegenstands-Notiz</span>
                            <p style="font-size:13.5px;">${summaries.subject_summary || 'Keine Notizen.'}</p>
                        </div>
                        <div>
                            <span class="metric-details-label" style="font-weight:600; display:block; margin-bottom:6px;">Problem-Notiz</span>
                            <p style="font-size:13.5px;">${summaries.problems_summary || 'Keine Notizen.'}</p>
                        </div>
                    </div>
                </div>
            </div>
        `;

        projectDetailModal.classList.remove('hidden');
    }



    // --- Tab-Inhalt: Prompts-Editor ---
    const promptsForm = document.getElementById('prompts-form');
    const promptSystem = document.getElementById('prompt-system');
    const promptProject = document.getElementById('prompt-project');
    const promptPortfolio = document.getElementById('prompt-portfolio');

    async function loadPrompts() {
        try {
            const res = await fetch('/api/prompts');
            if (!res.ok) throw new Error('Memos konnten nicht geladen werden.');
            const data = await res.json();
            
            promptSystem.value = data.system_prompt || '';
            promptProject.value = data.project_analysis_prompt || '';
            promptPortfolio.value = data.portfolio_analysis_prompt || '';
        } catch (err) {
            console.error(err);
            showToast('Prompts konnten nicht geladen werden.', 'error');
        }
    }

    promptsForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const payload = {
            system_prompt: promptSystem.value,
            project_analysis_prompt: promptProject.value,
            portfolio_analysis_prompt: promptPortfolio.value
        };

        try {
            const res = await fetch('/api/prompts', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) throw new Error('Prompts konnten nicht gespeichert werden.');
            showToast('KI-Prompts erfolgreich gespeichert.', 'success');
        } catch (err) {
            console.error(err);
            showToast(`Fehler beim Speichern der Prompts: ${err.message}`, 'error');
        }
    });

    // --- Tab-Inhalt: Einstellungen ---
    const settingsForm = document.getElementById('settings-form');
    
    // Einstellungsfelder
    const settingsBaUrl = document.getElementById('settings-ba-url');
    const settingsBaTtl = document.getElementById('settings-ba-ttl');
    const settingsOlUrl = document.getElementById('settings-ol-url');
    const settingsOlModel = document.getElementById('settings-ol-model');
    const settingsOlRetries = document.getElementById('settings-ol-retries');
    const settingsOlTimeout = document.getElementById('settings-ol-timeout');
    async function loadSettings() {
        try {
            const res = await fetch('/api/config');
            if (!res.ok) throw new Error('Verbindungskonfigurationen konnten nicht geladen werden.');
            const data = await res.json();

            if (data.blueant) {
                settingsBaUrl.value = data.blueant.url || '';
                settingsBaTtl.value = data.blueant.cache_ttl || 600;
            }
            if (data.ollama) {
                settingsOlUrl.value = data.ollama.url || '';
                settingsOlModel.value = data.ollama.model || '';
                settingsOlRetries.value = data.ollama.retries || 3;
                settingsOlTimeout.value = data.ollama.timeout || 120;
            }
        } catch (err) {
            console.error(err);
            showToast('Systemkonfigurationen konnten nicht geladen werden.', 'error');
        }
    }

    settingsForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const payload = {
            blueant: {
                url: settingsBaUrl.value.trim(),
                cache_ttl: parseInt(settingsBaTtl.value, 10) || 600
            },
            ollama: {
                url: settingsOlUrl.value.trim(),
                model: settingsOlModel.value.trim(),
                retries: parseInt(settingsOlRetries.value, 10) || 3,
                timeout: parseInt(settingsOlTimeout.value, 10) || 120
            }
        };

        try {
            const res = await fetch('/api/config', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) throw new Error('Speichern fehlgeschlagen.');
            showToast('Systemkonfigurationen erfolgreich gespeichert.', 'success');
        } catch (err) {
            console.error(err);
            showToast(`Fehler beim Speichern: ${err.message}`, 'error');
        }
    });

    // --- Start-Initialisierung ---
    updateTokenButtonState();
    loadPortfolios();
});
