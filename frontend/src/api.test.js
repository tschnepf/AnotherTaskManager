import { afterEach, describe, expect, it, vi } from 'vitest'

import { configureAuthHandlers, getTasks } from './api'

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
