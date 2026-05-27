import { getGitLabAuthStatus, startGitLabDeviceFlow } from '../gitlab-auth';

jest.mock('@jupyterlab/coreutils', () => ({
  PageConfig: { getBaseUrl: jest.fn(() => 'http://localhost:8888/') },
  URLExt: {
    join: (...parts: string[]) => {
      let result = parts[0].replace(/\/$/, '');
      for (let i = 1; i < parts.length; i++) {
        result += '/' + parts[i].replace(/^\//, '');
      }
      return result;
    }
  }
}));

const BASE = 'http://localhost:8888/api/oauth-providers/gitlab/';

function mockFetch(status: number, body: unknown): void {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    status,
    ok: status >= 200 && status < 300,
    json: () => Promise.resolve(body)
  });
}

beforeEach(() => {
  (global.fetch as jest.Mock) = jest.fn();
  Object.defineProperty(document, 'cookie', { value: '', writable: true });
});

// ---------------------------------------------------------------------------
// getGitLabAuthStatus
// ---------------------------------------------------------------------------

describe('getGitLabAuthStatus', () => {
  it('returns parsed body on 200', async () => {
    const payload = { connected: true, username: 'alice', email: 'alice@example.com' };
    mockFetch(200, payload);
    expect(await getGitLabAuthStatus()).toEqual(payload);
    expect(fetch).toHaveBeenCalledWith(
      BASE + 'status',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('returns null on 404 (extension not installed)', async () => {
    mockFetch(404, {});
    expect(await getGitLabAuthStatus()).toBeNull();
  });

  it('returns { connected: false } on 500', async () => {
    mockFetch(500, {});
    expect(await getGitLabAuthStatus()).toEqual({ connected: false });
  });

  it('returns { connected: false } when fetch throws', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('network'));
    expect(await getGitLabAuthStatus()).toEqual({ connected: false });
  });
});

// ---------------------------------------------------------------------------
// startGitLabDeviceFlow
// ---------------------------------------------------------------------------

describe('startGitLabDeviceFlow', () => {
  const devicePayload = {
    user_code: 'ABCD-1234',
    verification_uri: 'https://gitlab.com/oauth/device',
    device_code: 'dev-code-xyz',
    expires_in: 300,
    interval: 5,
    correlation_id: 'corr-1'
  };

  it('returns device payload on 200', async () => {
    mockFetch(200, devicePayload);
    expect(await startGitLabDeviceFlow()).toEqual(devicePayload);
    expect(fetch).toHaveBeenCalledWith(
      BASE + 'device/start',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('returns null on non-OK response', async () => {
    mockFetch(400, {});
    expect(await startGitLabDeviceFlow()).toBeNull();
  });

  it('returns null when fetch throws', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('network'));
    expect(await startGitLabDeviceFlow()).toBeNull();
  });

  it('includes X-XSRFToken header when _xsrf cookie is present', async () => {
    Object.defineProperty(document, 'cookie', { value: '_xsrf=test-token', writable: true });
    mockFetch(200, devicePayload);
    await startGitLabDeviceFlow();
    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-XSRFToken': 'test-token' })
      })
    );
  });

  it('omits X-XSRFToken header when _xsrf cookie is absent', async () => {
    mockFetch(200, devicePayload);
    await startGitLabDeviceFlow();
    const headers = (fetch as jest.Mock).mock.calls[0][1].headers;
    expect(headers).not.toHaveProperty('X-XSRFToken');
  });
});
