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

export interface IGitLabAuthStatus {
  connected: boolean;
  username?: string;
  display_name?: string;
  email?: string;
  user_id?: number;
  reconnect_required?: boolean;
  provider_url?: string;
}

function authApiUrl(path: string): string {
  return URLExt.join(PageConfig.getBaseUrl(), 'api/oauth-providers/gitlab', path);
}

/**
 * Returns the current GitLab auth status for the authenticated session.
 *
 * Returns null only on HTTP 404 (extension not installed) — callers hide the
 * GitLab section entirely in that case.
 * Returns { connected: false } on transient errors so the connect card stays visible.
 */
export async function getGitLabAuthStatus(): Promise<IGitLabAuthStatus | null> {
  try {
    const response = await fetch(authApiUrl('status'), {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }
    });
    if (response.status === 404) {
      return null; // auth extension not installed
    }
    if (!response.ok) {
      return { connected: false }; // transient error — keep UI visible
    }
    return (await response.json()) as IGitLabAuthStatus;
  } catch {
    return { connected: false }; // network error — keep UI visible
  }
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
export async function startGitLabDeviceFlow(): Promise<{
  user_code: string;
  verification_uri: string;
  verification_uri_complete?: string;
  device_code: string;
  expires_in: number;
  interval: number;
  correlation_id: string;
} | null> {
  try {
    const xsrf = xsrfToken();
    const response = await fetch(authApiUrl('device/start'), {
      method: 'POST',
      credentials: 'same-origin',
      body: JSON.stringify({}),
      headers: {
        'Content-Type': 'application/json',
        ...(xsrf ? { 'X-XSRFToken': xsrf } : {})
      }
    });
    if (!response.ok) {
      return null;
    }
    return response.json();
  } catch {
    return null;
  }
}
