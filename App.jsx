import React, { useState } from 'react';

export default function App() {
  const [activeTab, setActiveTab] = useState('Design Console');
  const [workspaceParams, setWorkspaceParams] = useState({
    product_domain: 'Fintech & Wealth Management',
    product_description: 'An AI-powered portfolio rebalancing tool for retail investors.',
    target_audience: 'Retail investors aged 25-55 seeking passive wealth growth.',
    research_objective: 'Understand user friction points during automated onboarding.',
    persona_count: 0
  });

  const [syntheticCohort, setSyntheticCohort] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [savedHistories, setSavedHistories] = useState([]);
  const [envStatus, setEnvStatus] = useState('IDLE');

  // Survey State
  const [surveyQuestion, setSurveyQuestion] = useState('');
  const [surveyResults, setSurveyResults] = useState([]);
  const [isSurveyRunning, setIsSurveyRunning] = useState(false);

  // Interview Mode State
  const [selectedPersonaForInterview, setSelectedPersonaForInterview] = useState(null);
  const [interviewHistory, setInterviewHistory] = useState([]); // [{ personaName, history: [{role, content}] }]
  const [interviewInput, setInterviewInput] = useState('');
  const [isInterviewLoading, setIsInterviewLoading] = useState(false);
  const [interviewInsights, setInterviewInsights] = useState(null);
  const [isInterviewInsightsLoading, setIsInterviewInsightsLoading] = useState(false);



  // Insight Analytics State
  const [finalInsights, setFinalInsights] = useState(null);
  const [isInsightsLoading, setIsInsightsLoading] = useState(false);
  const [validationReport, setValidationReport] = useState(null);
  const [isValidationLoading, setIsValidationLoading] = useState(false);
  const [isReportLoading, setIsReportLoading] = useState(false);

  const handleGenerateCohort = async () => {
    setIsProcessing(true);
    setEnvStatus('RUNNING_COHORT');
    try {
      const response = await fetch('http://localhost:8000/api/simulate-sandbox', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(workspaceParams)
      });
      const data = await response.json();
      if (response.ok) {
        setSyntheticCohort(data);
        setSurveyResults([]);
        setInterviewHistory([]);
        setInterviewInsights(null);
        setFinalInsights(null);
        setValidationReport(null);
      } else { alert('Error: ' + data.detail); }
    } catch (err) { alert('Failed to connect to backend server.'); }
    finally { setIsProcessing(false); setEnvStatus('IDLE'); }
  };

  const handleRunSurvey = async () => {
    if (syntheticCohort.length === 0) { alert('Please generate personas first.'); return; }
    if (!surveyQuestion.trim()) { alert('Please enter a survey question.'); return; }
    setIsSurveyRunning(true);
    setEnvStatus('RUNNING_SURVEY');
    try {
      const response = await fetch('http://localhost:8000/api/run-survey', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: surveyQuestion, cohort: syntheticCohort })
      });
      const data = await response.json();
      if (response.ok) { setSurveyResults(data.survey_results); }
      else { alert('Error: ' + data.detail); }
    } catch (err) { alert('Failed to connect to survey endpoint.'); }
    finally { setIsSurveyRunning(false); setEnvStatus('IDLE'); }
  };

  const handleSendInterviewMessage = async () => {
    if (!selectedPersonaForInterview || !interviewInput.trim()) return;
    const persona = selectedPersonaForInterview;
    const question = interviewInput;
    setInterviewInput('');

    let currentLog = interviewHistory.find(h => h.personaName === persona.name);
    let updatedMsgs = currentLog ? [...currentLog.history, { role: 'user', content: question }] : [{ role: 'user', content: question }];

    setIsInterviewLoading(true);
    try {
      const response = await fetch('http://localhost:8000/api/interview-turn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona, history: updatedMsgs, question })
      });
      const data = await response.json();
      if (response.ok) {
        updatedMsgs.push({ role: 'assistant', content: data.response });
        const filtered = interviewHistory.filter(h => h.personaName !== persona.name);
        setInterviewHistory([...filtered, { personaName: persona.name, history: updatedMsgs }]);
      } else { alert('Error: ' + data.detail); }
    } catch (err) { alert('Failed to reach interview endpoint.'); }
    finally { setIsInterviewLoading(false); }
  };

  const handleGenerateInsights = async () => {
    setIsInsightsLoading(true);
    try {
      const response = await fetch('http://localhost:8000/api/extract-insights', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          survey_results: surveyResults,
          interview_logs: interviewHistory,
          broadcast_results: [],
          workspace_params: workspaceParams
        })
      });
      const data = await response.json();
      if (response.ok) {
        setFinalInsights(data);
        setActiveTab('Insight Analytics');

      } else { alert('Error: ' + data.detail); }
    } catch (err) { alert('Failed to generate insights.'); }
    finally { setIsInsightsLoading(false); }
  };

  const handleGenerateInterviewInsights = async () => {
    if (!interviewHistory.length) { alert('Conduct at least one interview first.'); return; }
    setIsInterviewInsightsLoading(true);
    try {
      const response = await fetch('http://localhost:8000/api/extract-insights', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          survey_results: [],
          interview_logs: interviewHistory,
          broadcast_results: [],
          workspace_params: workspaceParams
        })
      });
      const data = await response.json();
      if (response.ok) {
        setInterviewInsights(data);
      } else { alert('Error: ' + data.detail); }
    } catch (err) { alert('Failed to generate interview insights.'); }
    finally { setIsInterviewInsightsLoading(false); }
  };

  const handleDownloadReport = async () => {
    if (syntheticCohort.length === 0) { alert('Generate personas first.'); return; }
    setIsReportLoading(true);
    const reportWindow = window.open('', '_blank');
    if (!reportWindow) {
      alert('Please allow pop-ups to open the research report.');
      setIsReportLoading(false);
      return;
    }
    reportWindow.document.title = 'Research Report';
    try {
      const response = await fetch('http://localhost:8000/api/download-report', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_params: workspaceParams, cohort: syntheticCohort, survey_results: surveyResults, interview_logs: interviewHistory, broadcast_results: [], insights: finalInsights, validation_report: validationReport })
      });
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || 'Research report could not be generated.'); }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      reportWindow.location.href = url;
      setTimeout(() => window.URL.revokeObjectURL(url), 60000);
    } catch (err) { reportWindow.close(); alert(err.message || 'Failed to open research report.'); }
    finally { setIsReportLoading(false); }
  };

  const handleSaveHistory = async () => {
    if (syntheticCohort.length === 0) {
      alert('Generate a synthetic cohort before saving history.');
      return;
    }

    try {
      const response = await fetch('http://localhost:8000/api/save-history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_params: workspaceParams,
          cohort: syntheticCohort,
          survey_results: surveyResults,
          interview_logs: interviewHistory,
          broadcast_results: [],
          insights: finalInsights
        })
      });
      const data = await response.json();
      if (!response.ok) {
        alert('Error: ' + data.detail);
        return;
      }

      setSavedHistories(prev => [...prev, data.history]);
      alert('Current research session saved successfully.');
      setActiveTab('Save History');
    } catch (err) {
      alert('Failed to save history.');
    }
  };

  const handleDeleteHistory = async (historyId) => {
    try {
      const response = await fetch(`http://localhost:8000/api/saved-histories/${historyId}`, { method: 'DELETE' });
      const data = await response.json();
      if (!response.ok) { alert('Delete error: ' + data.detail); return; }
      setSavedHistories(prev => prev.filter(h => h.id !== historyId));
    } catch (err) { alert('Failed to delete saved history.'); }
  };

  const handleLoadSavedHistories = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/saved-histories');
      const data = await response.json();
      if (response.ok) setSavedHistories(data.histories || []);
    } catch (err) {
      alert('Failed to load saved history.');
    }
  };

  const handleValidateInsights = async () => {
    if (syntheticCohort.length === 0) {
      alert('Generate a synthetic cohort first.');
      return;
    }
    if (!finalInsights && !surveyResults.length && !interviewHistory.length) {
      alert('Run at least one research activity before validation.');
      return;
    }

    setIsValidationLoading(true);
    try {
      const scenarios = [
        {
          name: 'Baseline Research Scenario',
          question: surveyQuestion || 'Would you use this product?',
          survey_results: surveyResults,
          interview_logs: interviewHistory,
          broadcast_results: [],
          expected_focus: workspaceParams.research_objective
        },
        {
          name: 'Risk & Trust Scenario',
          question: 'What would make you hesitate to use this product?',
          persona_focus: syntheticCohort.map(p => ({
            name: p.name,
            risk_tier: p.risk_tier,
            tech_adoption_level: p.tech_adoption_level
          }))
        },
        {
          name: 'Adoption Scenario',
          question: 'Would you use this product regularly? Why or why not?',
          persona_focus: syntheticCohort.map(p => ({
            name: p.name,
            goals: p.goals,
            pain_points: p.pain_points
          }))
        }
      ];

      const response = await fetch('http://localhost:8000/api/validate-insights', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_params: workspaceParams,
          cohort: syntheticCohort,
          scenarios
        })
      });
      const data = await response.json();
      if (response.ok) {
        setValidationReport(data);
      } else {
        alert('Validation error: ' + data.detail);
      }
    } catch (err) {
      alert('Failed to validate insights.');
    } finally {
      setIsValidationLoading(false);
    }
  };



  return (
    <div style={{ backgroundColor: '#0A0E17', color: '#F1F5F9', minHeight: '100vh', display: 'flex', fontFamily: 'Segoe UI, sans-serif' }}>
      
      {/* Left Navigation Menu Bar (Home View Removed) */}
      <div style={{ width: '230px', backgroundColor: '#0A0E17', borderRight: '1px solid #1E293B', padding: '20px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ marginBottom: '30px' }}>
          <h2 style={{ fontSize: '13px', color: '#94A3B8', margin: '0 0 4px 0', letterSpacing: '1px' }}>NAV MENU</h2>
          <span style={{ fontSize: '11px', color: '#38BDF8', fontWeight: 'bold' }}>SYNTHETIC PLATFORM</span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {[
            'Design Console',
            'Interview Mode',
            'Insight Analytics',
            'Save History',
            'Process Status Logs'
          ].map((item) => {
            const isSelected = activeTab.startsWith(item.split(' ')[0]);
            return (
              <button key={item} onClick={() => setActiveTab(item)}
                style={{
                  textAlign: 'left', padding: '10px 12px', borderRadius: '6px', border: 'none',
                  background: isSelected ? '#1E293B' : 'transparent', color: isSelected ? '#38BDF8' : '#94A3B8',
                  cursor: 'pointer', fontSize: '13px', fontWeight: isSelected ? '600' : 'normal'
                }}>
                {item}
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Content Pane */}
      <div style={{ flex: 1, padding: '30px', overflowY: 'auto' }}>
        <div style={{ textAlign: 'center', marginBottom: '25px' }}>
          <h1 style={{ margin: 0, fontSize: '22px', color: '#F8FAFC', fontWeight: 'bold' }}>Synthetic User Generation Platform</h1>
        </div>

        {/* 1. DESIGN CONSOLE */}
        {activeTab.startsWith('Design Console') && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1E293B', paddingBottom: '15px', marginBottom: '25px' }}>
              <div>
                <h2 style={{ margin: '0 0 5px 0', fontSize: '18px', color: '#F8FAFC' }}>Simulation Dashboard Console</h2>
                <span style={{ fontSize: '12px', color: '#34D399' }}>Active Cohort Size: {syntheticCohort.length}</span>
              </div>
              <span style={{ backgroundColor: envStatus === 'IDLE' ? '#064E3B' : '#7F1D1D', color: envStatus === 'IDLE' ? '#34D399' : '#FCA5A5', padding: '6px 12px', borderRadius: '6px', fontSize: '12px', fontWeight: 'bold' }}>● {envStatus}</span>
            </div>

            <div style={{ backgroundColor: '#111827', border: '1px solid #1F2937', borderRadius: '10px', padding: '20px', marginBottom: '30px' }}>
              <h3 style={{ marginTop: 0, fontSize: '15px', color: '#F8FAFC', textAlign: 'center', marginBottom: '20px' }}>⚙️ Workspace Parameters</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                <div>
                  <label style={{ fontSize: '10px', color: '#94A3B8', fontWeight: 'bold' }}>PRODUCT DOMAIN</label>
                  <input type="text" value={workspaceParams.product_domain} onChange={(e) => setWorkspaceParams({...workspaceParams, product_domain: e.target.value})}
                    style={{ width: '100%', padding: '10px', marginTop: '5px', backgroundColor: '#0B0F17', color: '#FFF', border: '1px solid #334155', borderRadius: '6px', boxSizing: 'border-box' }} />
                </div>
                <div>
                  <label style={{ fontSize: '10px', color: '#94A3B8', fontWeight: 'bold' }}>PRODUCT DESCRIPTION</label>
                  <textarea rows="2" value={workspaceParams.product_description} onChange={(e) => setWorkspaceParams({...workspaceParams, product_description: e.target.value})}
                    style={{ width: '100%', padding: '10px', marginTop: '5px', backgroundColor: '#0B0F17', color: '#FFF', border: '1px solid #334155', borderRadius: '6px', boxSizing: 'border-box', resize: 'none' }} />
                </div>
                <div>
                  <label style={{ fontSize: '10px', color: '#94A3B8', fontWeight: 'bold' }}>TARGET AUDIENCE</label>
                  <input type="text" value={workspaceParams.target_audience} onChange={(e) => setWorkspaceParams({...workspaceParams, target_audience: e.target.value})}
                    style={{ width: '100%', padding: '10px', marginTop: '5px', backgroundColor: '#0B0F17', color: '#FFF', border: '1px solid #334155', borderRadius: '6px', boxSizing: 'border-box' }} />
                </div>
                <div>
                  <label style={{ fontSize: '10px', color: '#94A3B8', fontWeight: 'bold' }}>RESEARCH OBJECTIVE</label>
                  <textarea rows="2" value={workspaceParams.research_objective} onChange={(e) => setWorkspaceParams({...workspaceParams, research_objective: e.target.value})}
                    style={{ width: '100%', padding: '10px', marginTop: '5px', backgroundColor: '#0B0F17', color: '#FFF', border: '1px solid #334155', borderRadius: '6px', boxSizing: 'border-box', resize: 'none' }} />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#38BDF8', fontWeight: 'bold' }}>PERSONA COUNT</label>
                  <div style={{ display: 'flex', gap: '15px', alignItems: 'center', marginTop: '5px' }}>
                    <input type="number" min="0" max="150" value={workspaceParams.persona_count} onChange={(e) => setWorkspaceParams({...workspaceParams, persona_count: Number(e.target.value)})}
                      style={{ width: '80px', padding: '10px', backgroundColor: '#0B0F17', color: '#38BDF8', border: '1px solid #334155', borderRadius: '6px', textAlign: 'center', fontWeight: 'bold' }} />
                    <button onClick={handleGenerateCohort} disabled={isProcessing}
                      style={{ flex: 1, padding: '12px', backgroundColor: isProcessing ? '#334155' : '#2563EB', color: '#FFF', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' }}>
                      {isProcessing ? 'Synthesizing Personas...' : 'Generate Synthetic Cohort'}
                    </button>
                  </div>
                </div>
              </div>

              {syntheticCohort.length > 0 && (
                <div style={{ marginTop: '30px' }}>
                  <h4 style={{ color: '#38BDF8', fontSize: '15px', marginBottom: '15px' }}>👥 Generated Cohort Cards ({syntheticCohort.length})</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px' }}>
                    {syntheticCohort.map((p, idx) => (
                      <div key={idx} style={{ backgroundColor: '#0B0F17', border: '1px solid #1F2937', borderRadius: '8px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        <h3 style={{ margin: 0, fontSize: '16px', color: '#38BDF8' }}>👤 {p.name}</h3>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1' }}><strong>Role:</strong> {p.role} | <strong>Age:</strong> {p.age}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1' }}>📍 <strong>Location:</strong> {p.location}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1', whiteSpace: 'pre-line', lineHeight: '1.45' }}>🧠 <strong>Psychology:</strong> {p.psychological_behavior}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1', whiteSpace: 'pre-line', lineHeight: '1.45' }}>🧩 <strong>Personality:</strong> {p.personality}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1', whiteSpace: 'pre-line', lineHeight: '1.45' }}>💻 <strong>Tech Level:</strong> {p.tech_adoption_level}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1', whiteSpace: 'pre-line', lineHeight: '1.45' }}>📢 <strong>Preferred Channel:</strong> {p.preferred_channel}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1', whiteSpace: 'pre-line', lineHeight: '1.45' }}>🎯 <strong>Goals:</strong> {p.goals}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1', whiteSpace: 'pre-line', lineHeight: '1.45' }}>⚠️ <strong>Pain Points:</strong> {p.pain_points}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1' }}>⚡ <strong>Risk Tier:</strong> {p.risk_tier}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1', whiteSpace: 'pre-line', lineHeight: '1.45' }}>👥 <strong>Target Audience:</strong> {p.target_audience}</p>
                        <p style={{ margin: 0, fontSize: '12px', color: '#CBD5E1', whiteSpace: 'pre-line', lineHeight: '1.45' }}>🔬 <strong>Research Objective:</strong> {p.research_objective}</p>
                        <p style={{ margin: 0, fontSize: '11px', color: '#94A3B8', fontStyle: 'italic', marginTop: '4px', whiteSpace: 'pre-line', lineHeight: '1.45' }}>"{p.memory_consistency_node}"</p>
                        
                        <button onClick={() => { setSelectedPersonaForInterview(p); setActiveTab('Interview Mode'); }}
                          style={{ marginTop: '10px', padding: '6px 12px', backgroundColor: '#1E293B', color: '#38BDF8', border: '1px solid #334155', borderRadius: '4px', cursor: 'pointer', fontSize: '12px', fontWeight: 'bold' }}>
                          💬 Start 1-on-1 Interview
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* SURVEY MODE */}
            {syntheticCohort.length > 0 && (
              <div style={{ backgroundColor: '#172033', border: '1px solid #334E68', borderRadius: '12px', padding: '25px', marginTop: '25px' }}>
                <h3 style={{ margin: '0 0 10px 0', fontSize: '18px', color: '#7DD3FC' }}>Survey Mode</h3>
                <textarea rows="2" placeholder="Type your question..." value={surveyQuestion} onChange={(e) => setSurveyQuestion(e.target.value)}
                  style={{ width: '100%', padding: '12px', backgroundColor: '#0B1220', color: '#FFF', border: '1px solid #3B526D', borderRadius: '6px', boxSizing: 'border-box', marginBottom: '15px', resize: 'none' }} />
                <button onClick={handleRunSurvey} disabled={isSurveyRunning}
                  style={{ width: '100%', padding: '12px', backgroundColor: isSurveyRunning ? '#7F1D1D' : '#2563EB', color: '#FFF', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' }}>
                  {isSurveyRunning ? 'Asking All Personas...' : '📢 Ask All Personas'}
                </button>
                {surveyResults.length > 0 && (
                  <div style={{ marginTop: '20px' }}>
                    <h4 style={{ margin: '0 0 15px 0', color: '#F8FAFC' }}>Survey Responses ({surveyResults.length})</h4>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '15px' }}>
                      {surveyResults.map((res, idx) => (
                        <div key={idx} style={{ backgroundColor: '#101A2B', border: '1px solid #334E68', padding: '15px', borderRadius: '8px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
                            <strong style={{ color: '#7DD3FC', fontSize: '14px' }}>{res.name}</strong>
                            <span style={{ color: res.sentiment === 'Negative' ? '#FCA5A5' : res.sentiment === 'Positive' ? '#6EE7B7' : '#CBD5E1', fontSize: '11px', fontWeight: 'bold' }}>{res.sentiment || 'Neutral'}</span>
                          </div>
                          <p style={{ margin: '8px 0 0 0', fontSize: '13px', color: '#E2E8F0', lineHeight: '1.55' }}>{res.response}</p>
                          <div style={{ marginTop: '10px', color: '#A5B4FC', fontSize: '12px', fontWeight: 'bold' }}>Would use this product: {Math.round(Number(res.would_use_score) || 0)}%</div>
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: '10px', marginTop: '18px', flexWrap: 'wrap' }}>
                      <button onClick={handleGenerateInsights} disabled={isInsightsLoading}
                        style={{ padding: '10px 18px', backgroundColor: '#0F766E', color: '#FFF', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' }}>
                        {isInsightsLoading ? 'Opening Insights...' : '📊 Insights & Scoring'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* 2. INTERVIEW MODE */}
        {activeTab.startsWith('Interview Mode') && (
          <div style={{ backgroundColor: '#111827', border: '1px solid #1F2937', borderRadius: '10px', padding: '20px' }}>
            <h2 style={{ color: '#38BDF8', marginTop: 0 }}>🎙️ Interview Mode</h2>
            {syntheticCohort.length === 0 ? (
              <p style={{ color: '#94A3B8' }}>Please generate a synthetic cohort in the Design Console first.</p>
            ) : (
              <div>
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ fontSize: '11px', color: '#94A3B8', fontWeight: 'bold' }}>SELECT PERSONA:</label>
                  <select value={selectedPersonaForInterview ? syntheticCohort.indexOf(selectedPersonaForInterview) : ''}
                    onChange={(e) => setSelectedPersonaForInterview(syntheticCohort[e.target.value])}
                    style={{ width: '100%', padding: '10px', marginTop: '5px', backgroundColor: '#0B0F17', color: '#FFF', border: '1px solid #334155', borderRadius: '6px' }}>
                    <option value="">-- Choose Persona --</option>
                    {syntheticCohort.map((p, i) => <option key={i} value={i}>{p.name} ({p.role})</option>)}
                  </select>
                </div>

                {selectedPersonaForInterview && (
                  <div style={{ backgroundColor: '#0B0F17', border: '1px solid #334155', borderRadius: '8px', padding: '15px' }}>
                    <h3 style={{ color: '#38BDF8', margin: '0 0 10px 0', fontSize: '15px' }}>Chat with {selectedPersonaForInterview.name}</h3>
                    <div style={{ height: '300px', overflowY: 'auto', border: '1px solid #1F2937', padding: '10px', borderRadius: '6px', marginBottom: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {((interviewHistory.find(h => h.personaName === selectedPersonaForInterview.name)?.history) || []).map((msg, idx) => (
                        <div key={idx} style={{ alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', backgroundColor: msg.role === 'user' ? '#2563EB' : '#1E293B', padding: '8px 12px', borderRadius: '8px', maxWidth: '80%', fontSize: '12px' }}>
                          <strong>{msg.role === 'user' ? 'You' : selectedPersonaForInterview.name}:</strong> {msg.content}
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input type="text" placeholder="Type question..." value={interviewInput} onChange={(e) => setInterviewInput(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSendInterviewMessage()}
                        style={{ flex: 1, padding: '8px', backgroundColor: '#111827', color: '#FFF', border: '1px solid #334155', borderRadius: '6px', fontSize: '12px' }} />
                      <button onClick={handleSendInterviewMessage} disabled={isInterviewLoading}
                        style={{ padding: '8px 14px', backgroundColor: '#2563EB', color: '#FFF', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer', fontSize: '12px' }}>
                        {isInterviewLoading ? '...' : 'Send'}
                      </button>
                    </div>
                    <div style={{ marginTop: '14px' }}>
                      <button onClick={handleGenerateInterviewInsights} disabled={isInterviewInsightsLoading}
                        style={{ padding: '10px 18px', backgroundColor: '#0F766E', color: '#FFF', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' }}>
                        {isInterviewInsightsLoading ? 'Analyzing Interview...' : '📊 Insight & Scoring'}
                      </button>
                    </div>
                    {interviewInsights && (
                      <div style={{ marginTop: '18px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                        <div style={{ backgroundColor: '#111827', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                          <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Recurring Themes</h3>
                          {(interviewInsights.recurring_themes || []).map((t, i) => <div key={i} style={{ color: '#CBD5E1', fontSize: '12px', marginBottom: '7px' }}><strong>{typeof t === 'string' ? t : t.theme}</strong>{typeof t !== 'string' && <span> — {t.description} (evidence: {t.evidence_count})</span>}</div>)}
                        </div>
                        <div style={{ backgroundColor: '#111827', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                          <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Theme Clusters</h3>
                          {(interviewInsights.theme_clusters || []).map((c, i) => <div key={i} style={{ color: '#CBD5E1', fontSize: '12px', marginBottom: '8px' }}><strong>{c.name}</strong> — {(c.themes || []).join(' · ')}<br/>{c.description}</div>)}
                        </div>
                        <div style={{ backgroundColor: '#111827', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                          <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Sentiment Breakdown</h3>
                          <div style={{ display: 'flex', gap: '10px', color: '#CBD5E1', fontSize: '12px', flexWrap: 'wrap' }}>
                            {['Positive', 'Negative', 'Neutral'].map(k => <span key={k} style={{ backgroundColor: '#1E293B', padding: '6px 12px', borderRadius: '6px' }}><strong>{k}:</strong> {interviewInsights.sentiment_breakdown?.[k] ?? 0}%</span>)}
                          </div>
                        </div>
                        <div style={{ backgroundColor: '#111827', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                          <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Agreement / Disagreement Patterns</h3>
                          {(interviewInsights.agreement_patterns || []).map((a, i) => <div key={i} style={{ color: '#CBD5E1', fontSize: '12px', marginBottom: '8px' }}><strong>{a.topic}</strong> — {a.agreement_level}<br/>{a.summary}<br/><span style={{ color: '#94A3B8' }}>Agreement: {(a.agreeing_personas || []).join(', ')} · Dissent: {(a.dissenting_personas || []).join(', ')}</span></div>)}
                        </div>
                        <div style={{ backgroundColor: '#111827', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                          <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Behavioral Trends</h3>
                          {(interviewInsights.behavioral_trends || []).map((b, i) => <div key={i} style={{ color: '#CBD5E1', fontSize: '12px', marginBottom: '8px' }}><strong>{b.trend}</strong> — {b.description}<br/><strong>Implication:</strong> {b.implication}<br/><span style={{ color: '#94A3B8' }}>Personas: {(b.affected_personas || []).join(', ')}</span></div>)}
                        </div>
                        <div style={{ backgroundColor: '#111827', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                          <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Would Use This Product — Individual Scoring</h3>
                          {(interviewInsights.adoption_scoring || []).map((a, i) => <div key={i} style={{ color: '#CBD5E1', fontSize: '12px', marginBottom: '7px' }}><strong>{a.persona_name}</strong> — {a.would_use_score}%<br/>{a.reasoning}</div>)}
                        </div>
                        <div style={{ backgroundColor: '#111827', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                          <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Would Use — Persona Segment Scoring</h3>
                          {(interviewInsights.segment_adoption_scoring || []).map((s, i) => <div key={i} style={{ color: '#CBD5E1', fontSize: '12px', marginBottom: '7px' }}><strong>{s.segment}</strong> — {s.average_would_use_score}%<br/>Members: {s.member_count} · {s.reasoning}</div>)}
                        </div>
                        <div style={{ backgroundColor: '#111827', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                          <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Segment Breakdown</h3>
                          {(interviewInsights.segment_breakdown || []).map((s, i) => <div key={i} style={{ color: '#CBD5E1', fontSize: '12px', marginBottom: '7px' }}><strong>{s.segment}</strong> — {s.member_count} members · {s.percentage}%</div>)}
                        </div>
                        <div style={{ backgroundColor: '#111827', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                          <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Research Quality / Validation</h3>
                          <p style={{ color: '#CBD5E1', fontSize: '12px' }}>Theme Relevance: {interviewInsights.research_quality?.theme_relevance_score ?? 0}% · Evidence Coverage: {interviewInsights.research_quality?.evidence_coverage_score ?? 0}% · Persona Consistency: {interviewInsights.research_quality?.consistency_score ?? 0}% · Overall Quality: {interviewInsights.research_quality?.overall_score ?? 0}% · Confidence: {interviewInsights.research_quality?.confidence || '—'}</p>
                          {(interviewInsights.research_quality?.validation_notes || []).map((n, i) => <div key={i} style={{ color: '#94A3B8', fontSize: '11px' }}>- {n}</div>)}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* 3. INSIGHT ANALYTICS */}
        {activeTab.startsWith('Insight Analytics') && (
          <div style={{ backgroundColor: '#111827', border: '1px solid #1F2937', borderRadius: '10px', padding: '20px' }}>
            <h2 style={{ color: '#38BDF8', marginTop: 0 }}>Insight & Analytics</h2>
            {!finalInsights ? (
              <div>
                <p style={{ color: '#94A3B8' }}>No final insights synthesized yet. Run a survey, interview, or Ask All Personas, then generate insights.</p>
                <button onClick={handleGenerateInsights} disabled={isInsightsLoading}
                  style={{ marginTop: '10px', padding: '10px 20px', backgroundColor: '#059669', color: '#FFF', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' }}>
                  {isInsightsLoading ? 'Synthesizing...' : 'Generate Insights Now'}
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div style={{ backgroundColor: '#0B0F17', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                  <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Recurring Themes</h3>
                  <ul style={{ color: '#CBD5E1', margin: 0, paddingLeft: '20px', fontSize: '13px' }}>
                    {(finalInsights.recurring_themes || []).map((t, i) => (
                      <li key={i} style={{ marginBottom: '7px' }}>
                        <strong>{typeof t === 'string' ? t : t.theme}</strong>
                        {typeof t !== 'string' && <span> — {t.description} (evidence: {t.evidence_count})</span>}
                      </li>
                    ))}
                  </ul>
                </div>

                <div style={{ backgroundColor: '#0B0F17', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                  <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Sentiment Breakdown</h3>
                  <div style={{ display: 'flex', gap: '20px', color: '#CBD5E1', fontSize: '13px', flexWrap: 'wrap' }}>
                    {Object.entries(finalInsights.sentiment_breakdown || {}).map(([k, v]) => (
                      <span key={k} style={{ backgroundColor: '#1E293B', padding: '6px 12px', borderRadius: '6px' }}><strong>{k}:</strong> {v}</span>
                    ))}
                  </div>
                </div>

                <div style={{ backgroundColor: '#0B0F17', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                  <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Agreement / Disagreement Patterns</h3>
                  {(finalInsights.agreement_patterns || []).length === 0 ? (
                    <p style={{ color: '#64748B', fontSize: '12px' }}>Insufficient evidence for explicit agreement analysis.</p>
                  ) : (
                    (finalInsights.agreement_patterns || []).map((a, i) => (
                      <div key={i} style={{ backgroundColor: '#111827', padding: '10px', borderRadius: '6px', marginBottom: '8px' }}>
                        <strong style={{ color: '#A78BFA', fontSize: '12px' }}>{a.topic}</strong>
                        <p style={{ margin: '4px 0', color: '#CBD5E1', fontSize: '12px' }}>{a.summary}</p>
                        <span style={{ color: '#94A3B8', fontSize: '11px' }}>Agreement: {a.agreement_level}</span>
                      </div>
                    ))
                  )}
                </div>

                <div style={{ backgroundColor: '#0B0F17', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                  <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Behavioral Trends</h3>
                  {(finalInsights.behavioral_trends || []).map((t, i) => (
                    <div key={i} style={{ backgroundColor: '#111827', padding: '10px', borderRadius: '6px', marginBottom: '8px' }}>
                      <strong style={{ color: '#34D399', fontSize: '12px' }}>{t.trend}</strong>
                      <p style={{ margin: '4px 0', color: '#CBD5E1', fontSize: '12px' }}>{t.description}</p>
                      <span style={{ color: '#94A3B8', fontSize: '11px' }}>Implication: {t.implication}</span>
                    </div>
                  ))}
                </div>

                <div style={{ backgroundColor: '#0B0F17', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                  <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>“Would use this product?” — Individual Scoring</h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '10px' }}>
                    {(finalInsights.adoption_scoring || []).map((s, i) => (
                      <div key={i} style={{ backgroundColor: '#111827', padding: '12px', borderRadius: '6px', border: '1px solid #1F2937' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                          <strong style={{ color: '#34D399', fontSize: '13px' }}>{s.persona_name}</strong>
                          <span style={{ color: '#38BDF8', fontSize: '13px' }}>Score: {s.would_use_score}</span>
                        </div>
                        <p style={{ margin: 0, fontSize: '12px', color: '#94A3B8' }}>{s.reasoning}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div style={{ backgroundColor: '#0B0F17', padding: '15px', borderRadius: '8px', border: '1px solid #1F2937' }}>
                  <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>“Would use this product?” — Persona Segment Aggregation</h3>
                  {(finalInsights.segment_adoption_scoring || []).map((s, i) => (
                    <div key={i} style={{ backgroundColor: '#111827', padding: '12px', borderRadius: '6px', marginBottom: '8px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <strong style={{ color: '#A78BFA', fontSize: '13px' }}>{s.segment}</strong>
                        <span style={{ color: '#34D399', fontSize: '13px' }}>Average: {s.average_would_use_score}%</span>
                      </div>
                      <p style={{ margin: '5px 0 0 0', color: '#94A3B8', fontSize: '12px' }}>
                        Members: {s.member_count} — {s.reasoning}
                      </p>
                    </div>
                  ))}
                </div>

                <div style={{ backgroundColor: '#0B0F17', padding: '15px', borderRadius: '8px', border: '1px solid #334155' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3 style={{ color: '#38BDF8', marginTop: 0, fontSize: '15px' }}>Insight Quality Validation</h3>
                    <button onClick={handleValidateInsights} disabled={isValidationLoading}
                      style={{ padding: '8px 14px', backgroundColor: '#7C3AED', color: '#FFF', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer', fontSize: '12px' }}>
                      {isValidationLoading ? 'Validating...' : 'Validate Across Scenarios'}
                    </button>
                  </div>

                  {validationReport && (
                    <div style={{ marginTop: '12px' }}>
                      <p style={{ color: '#34D399', fontWeight: 'bold', fontSize: '13px' }}>
                        Overall Score: {validationReport.overall_score}/100 — {validationReport.overall_confidence}
                      </p>
                      {(validationReport.scenarios || []).map((s, i) => (
                        <div key={i} style={{ backgroundColor: '#111827', padding: '10px', borderRadius: '6px', marginBottom: '8px' }}>
                          <strong style={{ color: '#A78BFA', fontSize: '12px' }}>{s.scenario}</strong>
                          <p style={{ margin: '5px 0', color: '#CBD5E1', fontSize: '11px' }}>
                            Theme relevance: {s.theme_relevance_score}/100 · Evidence coverage: {s.evidence_coverage_score}/100 · Persona consistency: {s.persona_consistency_score}/100
                          </p>
                          {(s.key_findings || []).map((x, j) => <div key={j} style={{ color: '#94A3B8', fontSize: '11px' }}>• {x}</div>)}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div style={{ marginTop: '14px' }}>
                  <button onClick={handleDownloadReport} disabled={isReportLoading}
                    style={{ padding: '10px 18px', backgroundColor: '#7C3AED', color: '#FFF', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' }}>
                    {isReportLoading ? 'Preparing Report...' : '📄 Research Report'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 4. SAVE HISTORY */}
        {activeTab.startsWith('Save History') && (
          <div style={{ backgroundColor: '#111827', border: '1px solid #1F2937', borderRadius: '10px', padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ color: '#38BDF8', marginTop: 0 }}>💾 Saved Simulation History</h2>
              <button onClick={handleLoadSavedHistories}
                style={{ padding: '8px 14px', backgroundColor: '#1E293B', color: '#38BDF8', border: '1px solid #334155', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' }}>
                Refresh History
              </button>
            </div>

            <button onClick={handleSaveHistory} disabled={syntheticCohort.length === 0}
              style={{ marginBottom: '15px', padding: '10px 18px', backgroundColor: '#059669', color: '#FFF', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' }}>
              💾 Save Current Session
            </button>

            {savedHistories.length === 0 ? (
              <p style={{ color: '#94A3B8' }}>No saved runs yet. Nothing is stored until you click “Save Current Session”.</p>
            ) : (
              savedHistories.map((h, i) => (
                <div key={h.id || i} style={{ backgroundColor: '#0B0F17', border: '1px solid #334155', borderRadius: '8px', padding: '15px', marginBottom: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <strong style={{ color: '#34D399', fontSize: '13px' }}>Saved Run #{h.id || i + 1}</strong>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><span style={{ color: '#64748B', fontSize: '11px' }}>{h.saved_at || 'Saved session'}</span><button onClick={() => handleDeleteHistory(h.id)} style={{ padding: '4px 8px', backgroundColor: '#7F1D1D', color: '#FCA5A5', border: '1px solid #991B1B', borderRadius: '4px', cursor: 'pointer', fontSize: '10px' }}>Delete</button></div>
                  </div>
                  <p style={{ color: '#CBD5E1', fontSize: '12px', margin: '7px 0' }}>
                    {h.workspace_params?.product_domain || 'Research'} · Cohort: {h.cohort?.length || 0} personas ·
                    Surveys: {h.survey_results?.length || 0} · Interviews: {h.interview_logs?.length || 0} ·
                    Broadcast responses: {h.broadcast_results?.length || 0}
                  </p>
                </div>
              ))
            )}
          </div>
        )}

        {/* PROCESS STATUS LOGS */}
        {activeTab.startsWith('Process Status Logs') && (
          <div style={{ backgroundColor: '#111827', border: '1px solid #1F2937', borderRadius: '10px', padding: '20px' }}>
            <h2 style={{ color: '#38BDF8', marginTop: 0 }}>📋 Process Status Logs</h2>
            <div style={{ backgroundColor: '#0B0F17', padding: '15px', borderRadius: '6px', fontFamily: 'monospace', fontSize: '12px', color: '#94A3B8' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '10px' }}>
                <div><span style={{ color: '#34D399' }}>Generated Personas:</span> {syntheticCohort.length}</div>
                <div><span style={{ color: '#34D399' }}>Survey Responses:</span> {surveyResults.length}</div>
                <div><span style={{ color: '#34D399' }}>Would Use:</span> {finalInsights?.would_use_summary?.would_use_count ?? surveyResults.filter(r => Number(r.would_use_score) >= 50).length}</div>
                <div><span style={{ color: '#FCA5A5' }}>Would Not Use:</span> {finalInsights?.would_use_summary?.would_not_use_count ?? surveyResults.filter(r => Number(r.would_use_score) < 50).length}</div>
                <div><span style={{ color: '#7DD3FC' }}>Average Product Fit:</span> {finalInsights?.average_product_fit != null ? Math.round(finalInsights.average_product_fit) + '%' : '—'}</div>
                <div><span style={{ color: '#FBBF24' }}>Research Quality:</span> {validationReport?.overall_score != null ? Math.round(validationReport.overall_score) + '%' : '—'}</div>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}