/**
 * gitlab-auth.ts
 *
 * Thin client for the jupyter-server-oauth-providers backend extension.
 * Used by GitPanel to resolve commit/push identity from the active GitLab session.
 *
 * Design: identity is NEVER read from or written to git config.
 * Instead, every commit resolves the author from the live GitLab session,
 * keyed to the Keycloak/oauth2-proxy user identity for this pod.
 */

import { PageConfig, URLExt } from '@jupyterlab/coreutils';

export type OAuthProvider = 'gitlab' | 'github';

export interface IOAuthStatus {
  connected: boolean;
  username?: string;
  display_name?: string;
  email?: string;
  user_id?: number;
  reconnect_required?: boolean;
  provider_url?: string;
}

export type IGitLabAuthStatus = IOAuthStatus;

function authApiUrl(provider: OAuthProvider, path: string): string {
  return URLExt.join(PageConfig.getBaseUrl(), `api/oauth-providers/${provider}`, path);
}

/**
 * Returns the current GitLab auth status for the authenticated session.
 *
 * Returns null only on HTTP 404 (extension not installed) — callers hide the
 * GitLab section entirely in that case.
 * Returns { connected: false } on transient errors so the connect card stays visible.
 */
export async function getOAuthStatus(provider: OAuthProvider): Promise<IOAuthStatus | null> {
  try {
    const response = await fetch(authApiUrl(provider, 'status'), {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }
    });
    if (response.status === 404) return null;
    if (!response.ok) return { connected: false };
    return (await response.json()) as IOAuthStatus;
  } catch {
    return { connected: false };
  }
}

export async function getGitLabAuthStatus(): Promise<IOAuthStatus | null> {
  return getOAuthStatus('gitlab');
}

export async function getGitHubAuthStatus(): Promise<IOAuthStatus | null> {
  return getOAuthStatus('github');
}

/** Cookie-based XSRF token reader. */
function xsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)_xsrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

/**
 * Starts the GitLab device authorization flow.
 * Returns null if the auth extension is not installed.
 */
export interface DeviceFlowStartResponse {
  user_code: string;
  verification_uri: string;
  verification_uri_complete?: string;
  device_code: string;
  expires_in: number;
  interval: number;
  correlation_id: string;
}

export async function startDeviceFlow(provider: OAuthProvider): Promise<DeviceFlowStartResponse | null> {
  try {
    const xsrf = xsrfToken();
    const response = await fetch(authApiUrl(provider, 'device/start'), {
      method: 'POST',
      credentials: 'same-origin',
      body: JSON.stringify({}),
      headers: {
        'Content-Type': 'application/json',
        ...(xsrf ? { 'X-XSRFToken': xsrf } : {})
      }
    });
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export async function startGitLabDeviceFlow(): Promise<DeviceFlowStartResponse | null> {
  return startDeviceFlow('gitlab');
}

export async function startGitHubDeviceFlow(): Promise<DeviceFlowStartResponse | null> {
  return startDeviceFlow('github');
}

export type DeviceFlowPollResult =
  | { status: 'approved'; username: string; email: string; slow_down?: boolean }
  | { status: 'pending'; slow_down?: boolean }
  | { status: 'expired'; slow_down?: boolean };

export async function pollDeviceFlow(
  provider: OAuthProvider,
  correlationId: string,
  deviceCode: string
): Promise<DeviceFlowPollResult> {
  const xsrf = xsrfToken();
  const response = await fetch(authApiUrl(provider, 'device/poll'), {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(xsrf ? { 'X-XSRFToken': xsrf } : {})
    },
    body: JSON.stringify({ correlation_id: correlationId, device_code: deviceCode })
  });
  if (!response.ok) throw new Error(`Poll failed: ${response.status}`);
  return response.json();
}

export async function pollGitLabDeviceFlow(correlationId: string, deviceCode: string): Promise<DeviceFlowPollResult> {
  return pollDeviceFlow('gitlab', correlationId, deviceCode);
}

export async function disconnect(provider: OAuthProvider): Promise<void> {
  const xsrf = xsrfToken();
  await fetch(authApiUrl(provider, 'disconnect'), {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(xsrf ? { 'X-XSRFToken': xsrf } : {})
    },
    body: JSON.stringify({})
  });
}

export async function disconnectGitLab(): Promise<void> {
  return disconnect('gitlab');
}
