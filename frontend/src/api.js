const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
const REFRESH_PATH = '/auth/refresh'
const CSRF_PATH = '/auth/csrf'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE'])

let authHandlers = {
  clearTokens: null,
}
let refreshPromise = null
let csrfPromise = null

export function configureAuthHandlers(handlers = {}) {
  authHandlers = {
    clearTokens: typeof handlers.clearTokens === 'function' ? handlers.clearTokens : null,
  }
}

function clearTokens() {
  if (typeof authHandlers.clearTokens === 'function') {
    authHandlers.clearTokens()
  }
}

function readCsrfTokenCookie() {
  if (typeof document === 'undefined') {
    return ''
  }

  const cookies = document.cookie ? document.cookie.split(';') : []
  for (const cookie of cookies) {
    const [name, ...rest] = cookie.trim().split('=')
    if (name === 'csrftoken') {
      return decodeURIComponent(rest.join('='))
    }
  }
  return ''
}

async function parseJsonBody(response) {
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    return null
  }
  return response.json()
}

async function ensureCsrfCookie() {
  const existingToken = readCsrfTokenCookie()
  if (existingToken) {
    return existingToken
  }
  if (csrfPromise) {
    return csrfPromise
  }

  csrfPromise = (async () => {
    const response = await fetch(`${API_BASE}${CSRF_PATH}`, {
      method: 'GET',
      credentials: 'include',
    })

    if (!response.ok) {
      throw new Error(`Failed to initialize CSRF protection (${response.status})`)
    }

    const data = await parseJsonBody(response)
    return readCsrfTokenCookie() || data?.csrfToken || ''
  })()

  try {
    return await csrfPromise
  } finally {
    csrfPromise = null
  }
}

async function refreshAccessToken() {
  if (refreshPromise) {
    return refreshPromise
  }

  refreshPromise = (async () => {
    try {
      const csrfToken = await ensureCsrfCookie()
      const headers = {
        'Content-Type': 'application/json',
      }
      if (csrfToken) {
        headers['X-CSRFToken'] = csrfToken
      }

      const response = await fetch(`${API_BASE}${REFRESH_PATH}`, {
        method: 'POST',
        credentials: 'include',
        headers,
        body: JSON.stringify({}),
      })

      if (!response.ok) {
        clearTokens()
        return false
      }
      return true
    } catch {
      clearTokens()
      return false
    }
  })()

  try {
    return await refreshPromise
  } finally {
    refreshPromise = null
  }
}

async function send(path, { method = 'GET', token, body, retryOnAuthFailure = true, signal } = {}) {
  const normalizedMethod = String(method || 'GET').toUpperCase()
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData
  const headers = {}

  if (!isFormData && body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }

  if (!SAFE_METHODS.has(normalizedMethod)) {
    const csrfToken = await ensureCsrfCookie()
    if (csrfToken) {
      headers['X-CSRFToken'] = csrfToken
    }
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method: normalizedMethod,
    credentials: 'include',
    headers,
    signal,
    body: body
      ? isFormData || typeof body === 'string'
        ? body
        : JSON.stringify(body)
      : undefined,
  })

  if (response.status === 401 && retryOnAuthFailure) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      return send(path, {
        method: normalizedMethod,
        token,
        body,
        signal,
        retryOnAuthFailure: false,
      })
    }
  }

  return response
}

async function request(path, { method = 'GET', token, body, signal } = {}) {
  const response = await send(path, { method, token, body, signal })
  const data = await parseJsonBody(response)

  if (!response.ok) {
    const message = data?.message || data?.detail || `Request failed (${response.status})`
    throw new Error(message)
  }

  return data
}

export async function getAuthSession() {
  return request('/auth/session', { method: 'GET' })
}

export async function login(email, password) {
  return request('/auth/login', { method: 'POST', body: { email, password } })
}

export async function logout() {
  return request('/auth/logout', {
    method: 'POST',
    body: {},
  })
}

export async function getTasks(token, params = {}) {
  const query = new URLSearchParams({
    page: '1',
    page_size: '50',
    sort: 'position',
    order: 'asc',
  })
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return
    }
    query.set(key, String(value))
  })
  return request(`/tasks/?${query.toString()}`, { token })
}

export async function getProjects(token, params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return
    }
    query.set(key, String(value))
  })
  const suffix = query.toString()
  const path = suffix ? `/projects/?${suffix}` : '/projects/'
  return request(path, { token })
}

export async function createProject(token, name, area = 'work') {
  return request('/projects/', {
    method: 'POST',
    token,
    body: { name, area },
  })
}

export async function quickAddTask(
  token,
  title,
  area = 'work',
  projectId = '',
  priority = null,
  dueAt = null,
  recurrence = 'none'
) {
  const body = { title, area, status: 'inbox' }
  if (projectId) {
    body.project = projectId
  }
  if (priority !== null) {
    body.priority = priority
  }
  if (dueAt) {
    body.due_at = dueAt
  }
  body.recurrence = recurrence || 'none'
  return request('/tasks/', {
    method: 'POST',
    token,
    body,
  })
}

export async function updateTask(token, taskId, payload) {
  return request(`/tasks/${taskId}/`, {
    method: 'PATCH',
    token,
    body: payload,
  })
}

export async function setTaskCompleted(token, taskId, completed) {
  const action = completed ? 'complete' : 'reopen'
  return request(`/tasks/${taskId}/${action}/`, {
    method: 'POST',
    token,
  })
}

export async function deleteTask(token, taskId) {
  return request(`/tasks/${taskId}/`, {
    method: 'DELETE',
    token,
  })
}

export async function reorderTask(token, taskId, targetTaskId, placement) {
  return request(`/tasks/${taskId}/reorder/`, {
    method: 'POST',
    token,
    body: { target_task_id: targetTaskId, placement },
  })
}

export async function waitForTaskChanges(
  token,
  { cursor = '', timeoutSeconds = 20, pollIntervalMs = 1000, signal } = {}
) {
  const query = new URLSearchParams({
    timeout_seconds: String(timeoutSeconds),
    poll_interval_ms: String(pollIntervalMs),
  })
  if (cursor) {
    query.set('cursor', cursor)
  }

  return request(`/tasks/changes/?${query.toString()}`, { token, signal })
}

export async function uploadTaskAttachment(token, taskId, file) {
  const body = new FormData()
  body.append('file', file)
  return request(`/tasks/${taskId}/attachments/upload/`, {
    method: 'POST',
    token,
    body,
  })
}

export async function downloadDatabaseBackup(token) {
  const response = await send('/ops/database/backup', { method: 'GET', token })

  if (!response.ok) {
    const data = await parseJsonBody(response)
    const message = data?.message || data?.detail || `Request failed (${response.status})`
    throw new Error(message)
  }

  const blob = await response.blob()
  const contentDisposition = response.headers.get('content-disposition') || ''
  const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/)
  const filename = filenameMatch?.[1] || 'taskhub-backup.json'
  return { blob, filename }
}

export async function restoreDatabaseBackup(token, backupFile, confirm = 'RESTORE') {
  const body = new FormData()
  body.append('backup_file', backupFile)
  body.append('confirm', confirm)
  return request('/ops/database/restore', {
    method: 'POST',
    token,
    body,
  })
}

export async function getEmailCaptureSettings(token) {
  return request('/settings/email-capture', { token })
}

export async function updateEmailCaptureSettings(
  token,
  {
    inboundEmailAddress,
    inboundEmailWhitelist,
    rotateToken,
    imapUsername,
    imapPassword,
    imapClearPassword,
    imapHost,
    imapProvider,
    imapPort,
    imapUseSsl,
    imapFolder,
    imapSearchCriteria,
    imapMarkSeenOnSuccess,
  }
) {
  return request('/settings/email-capture', {
    method: 'PATCH',
    token,
    body: {
      inbound_email_address: inboundEmailAddress,
      inbound_email_whitelist: inboundEmailWhitelist,
      rotate_token: Boolean(rotateToken),
      imap_username: imapUsername,
      imap_password: imapPassword,
      imap_clear_password: Boolean(imapClearPassword),
      imap_host: imapHost,
      imap_provider: imapProvider,
      imap_port: imapPort,
      imap_use_ssl: Boolean(imapUseSsl),
      imap_folder: imapFolder,
      imap_search_criteria: imapSearchCriteria,
      imap_mark_seen_on_success: Boolean(imapMarkSeenOnSuccess),
    },
  })
}

export async function initiateGoogleEmailOAuth(token) {
  return request('/settings/email-capture/oauth/google/initiate', {
    method: 'POST',
    token,
    body: {},
  })
}

export async function exchangeGoogleEmailOAuthCode(token, code, state) {
  return request('/settings/email-capture/oauth/google/exchange', {
    method: 'POST',
    token,
    body: { code, state },
  })
}

export async function disconnectGoogleEmailOAuth(token) {
  return request('/settings/email-capture/oauth/google/disconnect', {
    method: 'POST',
    token,
    body: {},
  })
}

export async function syncGoogleEmailOAuth(token, maxMessages = 10) {
  return request('/settings/email-capture/oauth/google/sync', {
    method: 'POST',
    token,
    body: { max_messages: maxMessages },
  })
}

export async function syncImapEmail(token, maxMessages = 25) {
  return request('/settings/email-capture/imap/sync', {
    method: 'POST',
    token,
    body: { max_messages: maxMessages },
  })
}
