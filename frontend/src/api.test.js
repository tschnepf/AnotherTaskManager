import { afterEach, describe, expect, it, vi } from 'vitest'

import { configureAuthHandlers, getTasks, waitForTaskChanges } from './api'

function jsonResponse(status, data) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: {
      get(name) {
        if (name.toLowerCase() === 'content-type') {
          return 'application/json'
        }
        return ''
      },
    },
    json: async () => data,
  }
}

afterEach(() => {
  configureAuthHandlers({
    getAccessToken: null,
    getRefreshToken: null,
    setTokens: null,
    clearTokens: null,
  })
  vi.restoreAllMocks()
})

describe('api token refresh', () => {
  it('refreshes and retries once on 401', async () => {
    const setTokens = vi.fn()
    configureAuthHandlers({
      getRefreshToken: () => 'old-refresh',
      setTokens,
    })

    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { message: 'Unauthorized' }))
      .mockResolvedValueOnce(jsonResponse(200, { access: 'new-access', refresh: 'new-refresh' }))
      .mockResolvedValueOnce(jsonResponse(200, { results: [], total: 0 }))

    const result = await getTasks('expired-access')

    expect(result.total).toBe(0)
    expect(setTokens).toHaveBeenCalledWith({ access: 'new-access', refresh: 'new-refresh' })
    expect(globalThis.fetch).toHaveBeenCalledTimes(3)
    expect(globalThis.fetch.mock.calls[2][1].headers.Authorization).toBe('Bearer new-access')
  })

  it('clears session when refresh fails', async () => {
    const clearTokens = vi.fn()
    configureAuthHandlers({
      getRefreshToken: () => 'stale-refresh',
      clearTokens,
    })

    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { message: 'Unauthorized' }))
      .mockResolvedValueOnce(jsonResponse(401, { message: 'Token is invalid or expired' }))

    await expect(getTasks('expired-access')).rejects.toThrow('Unauthorized')
    expect(clearTokens).toHaveBeenCalledTimes(1)
  })
})

describe('live task changes', () => {
  it('requests the changes endpoint with cursor and poll settings', async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce(jsonResponse(200, { changed: false, cursor: 'x' }))

    const result = await waitForTaskChanges('access-token', {
      cursor: 'abc:123',
      timeoutSeconds: 15,
      pollIntervalMs: 750,
    })

    expect(result).toEqual({ changed: false, cursor: 'x' })
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    expect(globalThis.fetch.mock.calls[0][0]).toContain(
      '/tasks/changes/?timeout_seconds=15&poll_interval_ms=750&cursor=abc%3A123'
    )
    expect(globalThis.fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer access-token')
  })
})
