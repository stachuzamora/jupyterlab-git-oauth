import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Dialog } from '@jupyterlab/apputils';
import { OAuthProvider, DeviceFlowStartResponse, pollDeviceFlow } from './gitlab-auth';

export type { DeviceFlowStartResponse };

type ModalState = 'waiting' | 'polling' | 'approved' | 'expired' | 'error';

function useCountdown(seconds: number, onExpire: () => void): number {
  const [remaining, setRemaining] = useState(seconds);
  useEffect(() => {
    if (remaining <= 0) { onExpire(); return; }
    const timer = window.setInterval(() => {
      setRemaining(r => {
        if (r <= 1) { clearInterval(timer); return 0; }
        return r - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return remaining;
}

function DeviceFlowModal({
  flow,
  provider,
  onSuccess,
  onCancel
}: {
  flow: DeviceFlowStartResponse;
  provider: OAuthProvider;
  onSuccess: (username: string, email: string) => void;
  onCancel: () => void;
}): JSX.Element {
  const [state, setState] = useState<ModalState>('waiting');
  const [errorMessage, setErrorMessage] = useState('');
  const [approvedUser, setApprovedUser] = useState('');
  const pollIntervalRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current !== null) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    setState('polling');
    let intervalMs = Math.max(flow.interval * 1000, 5000);

    const doPoll = async (): Promise<void> => {
      try {
        const result = await pollDeviceFlow(provider, flow.correlation_id, flow.device_code);
        if (result.status === 'approved') {
          stopPolling();
          window.dispatchEvent(new Event('oauth-providers:changed'));
          setState('approved');
          setApprovedUser(result.username || result.email || 'user');
          setTimeout(() => onSuccess(result.username ?? '', result.email ?? ''), 1200);
          return;
        }
        if (result.status === 'expired') { stopPolling(); setState('expired'); return; }
        if (result.slow_down) {
          intervalMs += 5000;
          stopPolling();
          pollIntervalRef.current = window.setInterval(doPoll, intervalMs);
        }
      } catch (err) {
        stopPolling();
        setState('error');
        setErrorMessage(err instanceof Error ? err.message : 'Unexpected polling error');
      }
    };

    pollIntervalRef.current = window.setInterval(doPoll, intervalMs);
  }, [flow, stopPolling, onSuccess]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const handleExpire = useCallback(() => { stopPolling(); setState('expired'); }, [stopPolling]);
  const remaining = useCountdown(flow.expires_in, handleExpire);

  const handleOpenGitLab = useCallback(() => {
    window.open(flow.verification_uri_complete || flow.verification_uri, '_blank', 'noopener,noreferrer');
    if (state === 'waiting') startPolling();
  }, [flow, state, startPolling]);

  const handleCancel = useCallback(() => { stopPolling(); onCancel(); }, [stopPolling, onCancel]);

  const minutes = Math.floor(remaining / 60);
  const secs = remaining % 60;
  const countdownText = `${minutes}:${String(secs).padStart(2, '0')}`;
  const codeColor = remaining < 60 ? '#cf222e' : 'inherit';

  const providerLabel = provider === 'github' ? 'GitHub' : 'GitLab';

  return (
    <div style={{ padding: '16px', minWidth: '340px', maxWidth: '420px', fontFamily: 'var(--jp-ui-font-family, sans-serif)' }}>
      <style>{`@keyframes oauth-spin { to { transform: rotate(360deg); } }`}</style>
      <h2 style={{ marginTop: 0, fontSize: '16px' }}>Connect to {providerLabel}</h2>

      {state === 'waiting' && (
        <>
          <p style={{ marginBottom: '8px' }}>Open GitLab and enter the code below to authorize this notebook.</p>
          <div style={{ background: '#f6f8fa', border: '2px solid #d0d7de', borderRadius: '8px', padding: '16px', textAlign: 'center', marginBottom: '16px' }}>
            <div style={{ fontSize: '11px', color: '#666', marginBottom: '4px' }}>Your device code</div>
            <div style={{ fontSize: '28px', fontFamily: 'monospace', fontWeight: 'bold', letterSpacing: '4px', color: '#1a1a2e' }}>{flow.user_code}</div>
          </div>
          <div style={{ textAlign: 'center', marginBottom: '12px' }}>
            <button className="jp-Button jp-mod-accept" onClick={handleOpenGitLab} style={{ fontSize: '13px', padding: '8px 20px' }}>Open GitLab to Authorize</button>
          </div>
          <p style={{ fontSize: '11px', color: '#666', textAlign: 'center' }}>Code expires in <strong style={{ color: codeColor }}>{countdownText}</strong></p>
        </>
      )}

      {state === 'polling' && (
        <>
          <div style={{ textAlign: 'center', marginBottom: '12px' }}>
            <div style={{ width: '36px', height: '36px', borderRadius: '50%', border: '4px solid #f0a500', borderTopColor: 'transparent', animation: 'oauth-spin 0.8s linear infinite', margin: '0 auto 12px' }} />
            <p>Waiting for GitLab authorization…</p>
            <p style={{ fontSize: '11px', color: '#666' }}>Approve code <strong style={{ fontFamily: 'monospace' }}>{flow.user_code}</strong> in the GitLab tab.</p>
          </div>
          <div style={{ textAlign: 'center', marginBottom: '12px' }}>
            <button className="jp-Button" onClick={handleOpenGitLab} style={{ fontSize: '12px' }}>Open GitLab Again</button>
          </div>
          <p style={{ fontSize: '11px', color: '#666', textAlign: 'center' }}>Code expires in <strong style={{ color: codeColor }}>{countdownText}</strong></p>
        </>
      )}

      {state === 'approved' && (
        <div style={{ textAlign: 'center', padding: '12px 0' }}>
          <div style={{ fontSize: '32px', marginBottom: '8px' }}>✓</div>
          <p style={{ color: '#2ea44f', fontWeight: 'bold' }}>Connected as {approvedUser}!</p>
          <p style={{ fontSize: '12px', color: '#666' }}>Closing…</p>
        </div>
      )}

      {state === 'expired' && (
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: '#cf222e' }}>The device code has expired. Please start the authorization flow again.</p>
        </div>
      )}

      {state === 'error' && (
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: '#cf222e' }}>An error occurred:</p>
          <p style={{ fontSize: '12px', fontFamily: 'monospace' }}>{errorMessage}</p>
        </div>
      )}

      {state !== 'approved' && (
        <div style={{ textAlign: 'right', marginTop: '12px' }}>
          <button className="jp-Button" onClick={handleCancel}>Cancel</button>
        </div>
      )}
    </div>
  );
}

export async function showDeviceFlowDialog(
  flow: DeviceFlowStartResponse,
  provider: OAuthProvider = 'gitlab'
): Promise<{ username: string; email: string } | null> {
  return new Promise(resolve => {
    let resolved = false;

    const handleSuccess = (username: string, email: string): void => {
      if (!resolved) { resolved = true; resolve({ username, email }); dialog.dispose(); }
    };
    const handleCancel = (): void => {
      if (!resolved) { resolved = true; resolve(null); dialog.dispose(); }
    };

    const dialog = new Dialog({ title: '', body: { getValue: () => null, node: document.createElement('div') } as any, buttons: [] });
    dialog.node.addEventListener('click', e => e.stopPropagation());
    dialog.launch().then(() => handleCancel());

    const bodyEl = dialog.node.querySelector('.jp-Dialog-body');
    if (bodyEl) {
      import('react-dom/client').then(({ createRoot }) => {
        createRoot(bodyEl).render(
          <DeviceFlowModal flow={flow} provider={provider} onSuccess={handleSuccess} onCancel={handleCancel} />
        );
      });
    }
  });
}
