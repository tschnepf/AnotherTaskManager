import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { PDFWorker, getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs'

import {
  configureAuthHandlers,
  createProject,
  deleteTask,
  disconnectGoogleEmailOAuth,
  downloadDatabaseBackup,
  exchangeGoogleEmailOAuthCode,
  getAuthSession,
  getEmailCaptureSettings,
  getProjects,
  getTasks,
  initiateGoogleEmailOAuth,
  logout as logoutSession,
  quickAddTask,
  reorderTask,
  restoreDatabaseBackup,
  setTaskCompleted,
  syncImapEmail,
  syncGoogleEmailOAuth,
  uploadTaskAttachment,
  updateEmailCaptureSettings,
  updateTask,
  waitForTaskChanges,
} from './api'
import './App.css'

const DAY_IN_MS = 24 * 60 * 60 * 1000
const LIVE_SYNC_TIMEOUT_SECONDS = 20
const LIVE_SYNC_POLL_INTERVAL_MS = 1000
const LIVE_SYNC_RETRY_DELAY_MS = 1500
const PRIORITY_OPTIONS = [
  { value: '', label: '-' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]
const RECURRENCE_OPTIONS = [
  { value: 'none', label: 'One-time' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]
const PREVIEWABLE_IMAGE_EXTENSIONS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'bmp',
  'avif',
])
const PREVIEWABLE_TEXT_EXTENSIONS = new Set([
  'eml',
  'txt',
  'md',
  'log',
  'json',
  'csv',
  'tsv',
  'xml',
  'yaml',
  'yml',
  'ini',
  'conf',
  'cfg',
  'ics',
  'vcf',
])
const TEXT_PREVIEW_BYTE_LIMIT = 2 * 1024 * 1024
const TEXT_PREVIEW_CHAR_LIMIT = 250000
const APP_SETTINGS_STORAGE_KEY = 'taskhub_app_settings_v1'
const DEFAULT_APP_SETTINGS = Object.freeze({
  profile: {
    displayName: '',
    replyToEmail: '',
    timezone: 'UTC',
  },
  emailCapture: {
    inboundAddress: '',
    inboundToken: '',
    whitelistInput: '',
    provider: 'imap',
    oauthEmail: '',
    oauthConnected: false,
    imapConfigured: false,
    imapUsername: '',
    imapPasswordInput: '',
    imapClearPassword: false,
    imapHost: '',
    imapProvider: 'auto',
    imapPort: '993',
    imapUseSsl: true,
    imapFolder: 'INBOX',
    imapSearchCriteria: 'UNSEEN',
    imapMarkSeenOnSuccess: true,
    rotateToken: false,
  },
  ai: {
    mode: 'off',
    allowCloudAi: false,
    redactSensitivePatterns: true,
    localBaseUrl: 'http://local-ai:8000',
  },
  taskList: {
    defaultArea: 'all',
    groupByPriorityDefault: false,
    areaTextColoringEnabled: false,
    workTextColor: '#93c5fd',
    personalTextColor: '#86efac',
  },
})

function cloneDefaultAppSettings() {
  return {
    profile: { ...DEFAULT_APP_SETTINGS.profile },
    emailCapture: { ...DEFAULT_APP_SETTINGS.emailCapture },
    ai: { ...DEFAULT_APP_SETTINGS.ai },
    taskList: { ...DEFAULT_APP_SETTINGS.taskList },
  }
}

function normalizeHexColor(value, fallback) {
  const normalized = String(value || '').trim()
  if (/^#[0-9a-fA-F]{6}$/.test(normalized)) {
    return normalized.toLowerCase()
  }
  return fallback
}

function loadAppSettings() {
  const defaults = cloneDefaultAppSettings()
  if (typeof window === 'undefined') {
    return defaults
  }

  try {
    const raw = window.localStorage.getItem(APP_SETTINGS_STORAGE_KEY)
    if (!raw) {
      return defaults
    }
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') {
      return defaults
    }

    return {
      profile: {
        displayName:
          typeof parsed.profile?.displayName === 'string'
            ? parsed.profile.displayName
            : defaults.profile.displayName,
        replyToEmail:
          typeof parsed.profile?.replyToEmail === 'string'
            ? parsed.profile.replyToEmail
            : defaults.profile.replyToEmail,
        timezone:
          typeof parsed.profile?.timezone === 'string'
            ? parsed.profile.timezone
            : defaults.profile.timezone,
      },
      emailCapture: {
        inboundAddress:
          typeof parsed.emailCapture?.inboundAddress === 'string'
            ? parsed.emailCapture.inboundAddress
            : defaults.emailCapture.inboundAddress,
        inboundToken: '',
        whitelistInput:
          typeof parsed.emailCapture?.whitelistInput === 'string'
            ? parsed.emailCapture.whitelistInput
            : defaults.emailCapture.whitelistInput,
        provider:
          typeof parsed.emailCapture?.provider === 'string'
            ? parsed.emailCapture.provider
            : defaults.emailCapture.provider,
        oauthEmail:
          typeof parsed.emailCapture?.oauthEmail === 'string'
            ? parsed.emailCapture.oauthEmail
            : defaults.emailCapture.oauthEmail,
        oauthConnected: Boolean(parsed.emailCapture?.oauthConnected),
        imapConfigured: Boolean(parsed.emailCapture?.imapConfigured),
        imapUsername:
          typeof parsed.emailCapture?.imapUsername === 'string'
            ? parsed.emailCapture.imapUsername
            : defaults.emailCapture.imapUsername,
        imapPasswordInput: '',
        imapClearPassword: false,
        imapHost:
          typeof parsed.emailCapture?.imapHost === 'string'
            ? parsed.emailCapture.imapHost
            : defaults.emailCapture.imapHost,
        imapProvider:
          typeof parsed.emailCapture?.imapProvider === 'string'
            ? parsed.emailCapture.imapProvider
            : defaults.emailCapture.imapProvider,
        imapPort:
          typeof parsed.emailCapture?.imapPort === 'string'
            ? parsed.emailCapture.imapPort
            : defaults.emailCapture.imapPort,
        imapUseSsl:
          typeof parsed.emailCapture?.imapUseSsl === 'boolean'
            ? parsed.emailCapture.imapUseSsl
            : defaults.emailCapture.imapUseSsl,
        imapFolder:
          typeof parsed.emailCapture?.imapFolder === 'string'
            ? parsed.emailCapture.imapFolder
            : defaults.emailCapture.imapFolder,
        imapSearchCriteria:
          typeof parsed.emailCapture?.imapSearchCriteria === 'string'
            ? parsed.emailCapture.imapSearchCriteria
            : defaults.emailCapture.imapSearchCriteria,
        imapMarkSeenOnSuccess:
          typeof parsed.emailCapture?.imapMarkSeenOnSuccess === 'boolean'
            ? parsed.emailCapture.imapMarkSeenOnSuccess
            : defaults.emailCapture.imapMarkSeenOnSuccess,
        rotateToken: false,
      },
      ai: {
        mode: typeof parsed.ai?.mode === 'string' ? parsed.ai.mode : defaults.ai.mode,
        allowCloudAi:
          typeof parsed.ai?.allowCloudAi === 'boolean'
            ? parsed.ai.allowCloudAi
            : defaults.ai.allowCloudAi,
        redactSensitivePatterns:
          typeof parsed.ai?.redactSensitivePatterns === 'boolean'
            ? parsed.ai.redactSensitivePatterns
            : defaults.ai.redactSensitivePatterns,
        localBaseUrl:
          typeof parsed.ai?.localBaseUrl === 'string'
            ? parsed.ai.localBaseUrl
            : defaults.ai.localBaseUrl,
      },
      taskList: {
        defaultArea:
          typeof parsed.taskList?.defaultArea === 'string'
            ? parsed.taskList.defaultArea
            : defaults.taskList.defaultArea,
        groupByPriorityDefault:
          typeof parsed.taskList?.groupByPriorityDefault === 'boolean'
            ? parsed.taskList.groupByPriorityDefault
            : defaults.taskList.groupByPriorityDefault,
        areaTextColoringEnabled:
          typeof parsed.taskList?.areaTextColoringEnabled === 'boolean'
            ? parsed.taskList.areaTextColoringEnabled
            : defaults.taskList.areaTextColoringEnabled,
        workTextColor: normalizeHexColor(
          parsed.taskList?.workTextColor,
          defaults.taskList.workTextColor
        ),
        personalTextColor: normalizeHexColor(
          parsed.taskList?.personalTextColor,
          defaults.taskList.personalTextColor
        ),
      },
    }
  } catch {
    return defaults
  }
}

function saveAppSettings(settings) {
  if (typeof window === 'undefined') {
    return
  }
  const persisted = {
    ...settings,
    emailCapture: {
      inboundAddress: settings.emailCapture?.inboundAddress || '',
      inboundToken: '',
      whitelistInput: settings.emailCapture?.whitelistInput || '',
      provider: settings.emailCapture?.provider || 'imap',
      oauthEmail: settings.emailCapture?.oauthEmail || '',
      oauthConnected: Boolean(settings.emailCapture?.oauthConnected),
      imapConfigured: Boolean(settings.emailCapture?.imapConfigured),
      imapUsername: settings.emailCapture?.imapUsername || '',
      imapPasswordInput: '',
      imapClearPassword: false,
      imapHost: settings.emailCapture?.imapHost || '',
      imapProvider: settings.emailCapture?.imapProvider || 'auto',
      imapPort: settings.emailCapture?.imapPort || '993',
      imapUseSsl: settings.emailCapture?.imapUseSsl !== false,
      imapFolder: settings.emailCapture?.imapFolder || 'INBOX',
      imapSearchCriteria: settings.emailCapture?.imapSearchCriteria || 'UNSEEN',
      imapMarkSeenOnSuccess: settings.emailCapture?.imapMarkSeenOnSuccess !== false,
      rotateToken: false,
    },
    taskList: {
      defaultArea: settings.taskList?.defaultArea || 'all',
      groupByPriorityDefault: Boolean(settings.taskList?.groupByPriorityDefault),
      areaTextColoringEnabled: Boolean(settings.taskList?.areaTextColoringEnabled),
      workTextColor: normalizeHexColor(
        settings.taskList?.workTextColor,
        DEFAULT_APP_SETTINGS.taskList.workTextColor
      ),
      personalTextColor: normalizeHexColor(
        settings.taskList?.personalTextColor,
        DEFAULT_APP_SETTINGS.taskList.personalTextColor
      ),
    },
  }
  window.localStorage.setItem(APP_SETTINGS_STORAGE_KEY, JSON.stringify(persisted))
}

function parseEmailWhitelistInput(rawInput) {
  const source = String(rawInput || '')
  const seen = new Set()
  return source
    .split(/[\n,]/g)
    .map((entry) => entry.trim().toLowerCase())
    .filter((entry) => entry)
    .filter((entry) => {
      if (seen.has(entry)) return false
      seen.add(entry)
      return true
    })
}

function emailCaptureSettingsFromApi(data) {
  const whitelist = Array.isArray(data?.inbound_email_whitelist) ? data.inbound_email_whitelist : []
  return {
    inboundAddress: String(data?.inbound_email_address || ''),
    inboundToken: String(data?.inbound_email_token || ''),
    whitelistInput: whitelist.join('\n'),
    provider: String(data?.inbound_email_mode || data?.inbound_email_provider || 'imap'),
    oauthEmail: String(data?.gmail_oauth_email || ''),
    oauthConnected: Boolean(data?.gmail_oauth_connected),
    imapConfigured: Boolean(data?.imap_configured),
    imapUsername: String(data?.imap_username || ''),
    imapPasswordInput: '',
    imapClearPassword: false,
    imapHost: String(data?.imap_host || ''),
    imapProvider: String(data?.imap_provider || 'auto'),
    imapPort: String(data?.imap_port || '993'),
    imapUseSsl: Boolean(data?.imap_use_ssl ?? true),
    imapFolder: String(data?.imap_folder || 'INBOX'),
    imapSearchCriteria: String(data?.imap_search_criteria || 'UNSEEN'),
    imapMarkSeenOnSuccess: Boolean(data?.imap_mark_seen_on_success ?? true),
    rotateToken: false,
  }
}

function initialTaskViewFromSettings(settings) {
  if (settings.taskList.defaultArea === 'work') {
    return { type: 'area', area: 'work' }
  }
  if (settings.taskList.defaultArea === 'personal') {
    return { type: 'area', area: 'personal' }
  }
  return { type: 'all' }
}

function priorityValueFromLevel(level) {
  if (level === 'high') return 5
  if (level === 'medium') return 3
  if (level === 'low') return 1
  return null
}

function priorityLevelFromValue(priority) {
  if (priority === null || priority === undefined) {
    return ''
  }
  if (priority >= 4) return 'high'
  if (priority >= 2) return 'medium'
  return 'low'
}

function priorityClassFromLevel(level) {
  if (level === 'high') return 'priority-text-high'
  if (level === 'medium') return 'priority-text-medium'
  if (level === 'low') return 'priority-text-low'
  return ''
}

function priorityLabelFromValue(priority) {
  const level = priorityLevelFromValue(priority)
  if (!level) {
    return 'No priority'
  }
  if (level === 'high') {
    return 'High'
  }
  if (level === 'medium') {
    return 'Medium'
  }
  return 'Low'
}

function dueAtFromDateInput(value) {
  if (!value) {
    return null
  }
  const [yearRaw, monthRaw, dayRaw] = String(value)
    .split('-')
    .map((part) => Number.parseInt(part, 10))
  if (!yearRaw || !monthRaw || !dayRaw) {
    return null
  }
  const localNoon = new Date(yearRaw, monthRaw - 1, dayRaw, 12, 0, 0, 0)
  if (Number.isNaN(localNoon.getTime())) {
    return null
  }
  return localNoon.toISOString()
}

function dateInputFromDueAt(value) {
  if (!value) {
    return ''
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return ''
  }
  const year = parsed.getFullYear()
  const month = String(parsed.getMonth() + 1).padStart(2, '0')
  const day = String(parsed.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatTaskDate(value) {
  if (!value) {
    return 'No date'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return 'No date'
  }
  return parsed.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function recurrenceLabel(value) {
  if (value === 'daily') return 'Daily'
  if (value === 'weekly') return 'Weekly'
  if (value === 'monthly') return 'Monthly'
  if (value === 'yearly') return 'Yearly'
  return 'One-time'
}

function formatAreaLabel(area) {
  if (area === 'work') return 'Work'
  if (area === 'personal') return 'Personal'
  return area
}

function normalizeAttachments(attachments) {
  if (!Array.isArray(attachments)) {
    return []
  }
  return attachments
    .map((attachment) => {
      if (!attachment || typeof attachment !== 'object') {
        return null
      }
      const name = String(attachment.name || '').trim()
      const path = String(attachment.path || '').trim()
      const rawUrl = String(attachment.url || '').trim()
      let url = rawUrl
      if (rawUrl) {
        try {
          const parsed = new URL(rawUrl, window.location.origin)
          if (parsed.pathname.startsWith('/tasks/attachments/file')) {
            url = `${window.location.origin}${parsed.pathname}${parsed.search}${parsed.hash}`
          }
        } catch {
          url = rawUrl
        }
      }
      if (!url) {
        return null
      }
      return { name: name || 'Attachment', path, url }
    })
    .filter(Boolean)
}

function attachmentExtension(attachment) {
  const name = String(attachment?.name || '').trim()
  const path = String(attachment?.path || '').trim()
  const url = String(attachment?.url || '').trim()
  const candidate = name || path || url
  if (!candidate) {
    return ''
  }

  let pathname = candidate
  try {
    pathname = new URL(candidate, window.location.origin).pathname
  } catch {
    pathname = candidate
  }

  const filename = pathname.split('/').pop() || pathname
  const dotIndex = filename.lastIndexOf('.')
  if (dotIndex <= 0 || dotIndex >= filename.length - 1) {
    return ''
  }
  return filename.slice(dotIndex + 1).toLowerCase()
}

function attachmentPreviewType(attachment) {
  const extension = attachmentExtension(attachment)
  if (!extension) {
    return ''
  }
  if (extension === 'pdf') {
    return 'pdf'
  }
  if (PREVIEWABLE_IMAGE_EXTENSIONS.has(extension)) {
    return 'image'
  }
  if (PREVIEWABLE_TEXT_EXTENSIONS.has(extension)) {
    return 'text'
  }
  return ''
}

function isModifiedLinkClick(event) {
  return (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.altKey ||
    event.shiftKey
  )
}

function EyeIcon() {
  return (
    <svg
      className="attachment-action-icon"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M2 12C3.8 8.6 7.4 6.5 12 6.5C16.6 6.5 20.2 8.6 22 12C20.2 15.4 16.6 17.5 12 17.5C7.4 17.5 3.8 15.4 2 12Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="2.8" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg
      className="attachment-action-icon"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M12 3.5V14.5M12 14.5L8.2 10.7M12 14.5L15.8 10.7"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M5 17.5H19V20.5H5V17.5Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function CogIcon() {
  return (
    <svg
      className="sidebar-settings-icon"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M12 8.2A3.8 3.8 0 1 1 12 15.8A3.8 3.8 0 0 1 12 8.2Z"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="M19 12A7.3 7.3 0 0 0 18.8 10.3L21 8.7L19.3 5.7L16.8 6.4A7.2 7.2 0 0 0 15.3 5.4L15 2.8H9L8.7 5.4A7.2 7.2 0 0 0 7.2 6.4L4.7 5.7L3 8.7L5.2 10.3A7.3 7.3 0 0 0 5 12C5 12.6 5.1 13.2 5.2 13.7L3 15.3L4.7 18.3L7.2 17.6C7.7 18 8.2 18.3 8.7 18.6L9 21.2H15L15.3 18.6C15.8 18.3 16.3 18 16.8 17.6L19.3 18.3L21 15.3L18.8 13.7C18.9 13.2 19 12.6 19 12Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function PdfCanvasViewer({ url, fileName }) {
  const containerRef = useRef(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    let loadingTask = null
    let pdfWorker = null
    const activeRenderTasks = []

    async function renderPdf() {
      setIsLoading(true)
      setError('')

      const container = containerRef.current
      if (!container) {
        setIsLoading(false)
        return
      }
      container.replaceChildren()

      try {
        const response = await fetch(url, { credentials: 'include' })
        if (!response.ok) {
          throw new Error(`Failed to load PDF (${response.status})`)
        }
        const pdfBytes = await response.arrayBuffer()

        // Prefer an explicit bundled worker so rendering doesn't depend on browser PDF behavior.
        try {
          const workerPort = new Worker(
            new URL('pdfjs-dist/legacy/build/pdf.worker.mjs', import.meta.url),
            { type: 'module' }
          )
          pdfWorker = new PDFWorker({ port: workerPort })
        } catch {
          pdfWorker = null
        }

        loadingTask = getDocument({
          data: pdfBytes,
          ...(pdfWorker ? { worker: pdfWorker } : {}),
        })
        const pdfDocument = await loadingTask.promise
        if (cancelled) {
          return
        }

        for (let pageNumber = 1; pageNumber <= pdfDocument.numPages; pageNumber += 1) {
          const page = await pdfDocument.getPage(pageNumber)
          if (cancelled) {
            return
          }

          const viewport = page.getViewport({ scale: 1.4 })
          const pageWrapper = document.createElement('div')
          pageWrapper.className = 'pdf-canvas-page'

          const canvas = document.createElement('canvas')
          canvas.className = 'pdf-canvas'
          canvas.width = Math.ceil(viewport.width)
          canvas.height = Math.ceil(viewport.height)

          const canvasContext = canvas.getContext('2d')
          if (!canvasContext) {
            throw new Error('Could not initialize PDF canvas')
          }

          pageWrapper.appendChild(canvas)
          container.appendChild(pageWrapper)

          const renderTask = page.render({ canvasContext, viewport })
          activeRenderTasks.push(renderTask)
          await renderTask.promise
        }

        if (!cancelled) {
          setIsLoading(false)
        }
      } catch (cause) {
        if (!cancelled) {
          const message = cause instanceof Error ? cause.message : 'Unable to preview this PDF.'
          setError(message)
          console.error('Task Hub PDF preview failed:', cause)
          setIsLoading(false)
        }
      }
    }

    renderPdf()

    return () => {
      cancelled = true
      activeRenderTasks.forEach((task) => {
        if (typeof task.cancel === 'function') {
          try {
            task.cancel()
          } catch {
            // Ignore cancellation errors while unmounting.
          }
        }
      })
      if (loadingTask) {
        loadingTask.destroy()
      }
      if (pdfWorker) {
        pdfWorker.destroy()
      }
    }
  }, [url])

  if (error) {
    return (
      <div className="pdf-viewer-error">
        <p>Unable to preview this PDF in-app.</p>
        <p className="pdf-viewer-error-detail">{error}</p>
        <a href={url} target="_blank" rel="noreferrer">
          Open in browser
        </a>
      </div>
    )
  }

  return (
    <div className="pdf-viewer-shell">
      {isLoading ? <p className="pdf-viewer-status">Loading PDF...</p> : null}
      <div
        ref={containerRef}
        className={isLoading ? 'pdf-canvas-list pdf-canvas-list-hidden' : 'pdf-canvas-list'}
        aria-label={`PDF preview for ${fileName}`}
      />
    </div>
  )
}

function TextAttachmentViewer({ url }) {
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [textContent, setTextContent] = useState('')
  const [isTruncated, setIsTruncated] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function loadTextAttachment() {
      setIsLoading(true)
      setError('')
      setTextContent('')
      setIsTruncated(false)

      try {
        const response = await fetch(url, { credentials: 'include' })
        if (!response.ok) {
          throw new Error(`Failed to load file (${response.status})`)
        }

        const contentLength = Number.parseInt(response.headers.get('content-length') || '', 10)
        if (Number.isFinite(contentLength) && contentLength > TEXT_PREVIEW_BYTE_LIMIT) {
          throw new Error('File is too large to preview in-app.')
        }

        const fullText = await response.text()
        if (cancelled) {
          return
        }

        if (fullText.length > TEXT_PREVIEW_CHAR_LIMIT) {
          setTextContent(fullText.slice(0, TEXT_PREVIEW_CHAR_LIMIT))
          setIsTruncated(true)
        } else {
          setTextContent(fullText)
        }
        setIsLoading(false)
      } catch (cause) {
        if (!cancelled) {
          const message = cause instanceof Error ? cause.message : 'Unable to preview this file.'
          setError(message)
          setIsLoading(false)
        }
      }
    }

    loadTextAttachment()
    return () => {
      cancelled = true
    }
  }, [url])

  if (error) {
    return (
      <div className="text-viewer-error">
        <p>Unable to preview this file in-app.</p>
        <p className="text-viewer-error-detail">{error}</p>
        <a href={url} target="_blank" rel="noreferrer">
          Open in browser
        </a>
      </div>
    )
  }

  return (
    <div className="text-viewer-shell">
      {isLoading ? <p className="text-viewer-status">Loading attachment...</p> : null}
      {!isLoading ? (
        <>
          <pre className="text-viewer-content">{textContent || 'This file is empty.'}</pre>
          {isTruncated ? (
            <p className="text-viewer-truncated">
              Preview truncated. Download the file to view the full content.
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

function HtmlAttachmentViewer({ url, title }) {
  return (
    <div className="html-viewer-shell">
      <iframe
        src={url}
        title={title ? `Preview ${title}` : 'HTML attachment preview'}
        className="html-viewer-frame"
        sandbox="allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation"
      />
    </div>
  )
}

function formatCreatedTimestamp(value) {
  if (!value) {
    return '—'
  }
  const createdAt = new Date(value)
  if (Number.isNaN(createdAt.getTime())) {
    return '—'
  }

  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const createdDayStart = new Date(
    createdAt.getFullYear(),
    createdAt.getMonth(),
    createdAt.getDate()
  )
  const dayDiff = Math.floor((todayStart.getTime() - createdDayStart.getTime()) / DAY_IN_MS)

  if (dayDiff <= 0) {
    return 'Today'
  }
  if (dayDiff === 1) {
    return 'Yesterday'
  }
  if (dayDiff <= 7) {
    return `${dayDiff} days ago`
  }
  if (dayDiff <= 30) {
    const weeks = Math.min(4, Math.floor(dayDiff / 7))
    return weeks === 1 ? '1 week ago' : `${weeks} weeks ago`
  }

  const months = Math.floor(dayDiff / 30)
  return months === 1 ? '1 month ago' : `${months} months ago`
}

function normalizedSortText(value) {
  return String(value || '').trim().toLocaleLowerCase()
}

function compareTaskTextValues(leftValue, rightValue) {
  return normalizedSortText(leftValue).localeCompare(normalizedSortText(rightValue), undefined, {
    numeric: true,
    sensitivity: 'base',
  })
}

function compareTaskDateValues(leftValue, rightValue, direction) {
  const leftTime = new Date(leftValue || '').getTime()
  const rightTime = new Date(rightValue || '').getTime()
  const leftIsValid = Number.isFinite(leftTime)
  const rightIsValid = Number.isFinite(rightTime)

  if (!leftIsValid && !rightIsValid) {
    return 0
  }
  if (!leftIsValid) {
    return 1
  }
  if (!rightIsValid) {
    return -1
  }
  return (leftTime - rightTime) * direction
}

function compareTaskPriorityValues(leftValue, rightValue, direction) {
  const rankFromPriority = (priorityValue) => {
    const level = priorityLevelFromValue(priorityValue)
    if (level === 'high') return 3
    if (level === 'medium') return 2
    if (level === 'low') return 1
    return 0
  }

  const leftRank = rankFromPriority(leftValue)
  const rightRank = rankFromPriority(rightValue)

  if (leftRank === 0 && rightRank === 0) {
    return 0
  }
  if (leftRank === 0) {
    return 1
  }
  if (rightRank === 0) {
    return -1
  }
  return (leftRank - rightRank) * direction
}

function AuthPage() {
  const location = useLocation()
  const [isRedirecting, setIsRedirecting] = useState(false)

  const params = new URLSearchParams(location.search)
  const error = params.get('error') || ''

  function handleOidcSignIn() {
    setIsRedirecting(true)
    const next = encodeURIComponent('/')
    window.location.assign(`/auth/oidc/start?next=${next}`)
  }

  function handleCreateAccount() {
    setIsRedirecting(true)
    const next = encodeURIComponent('/')
    window.location.assign(`/auth/oidc/start?next=${next}&signup=1`)
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <h1>Task Hub</h1>
        <p>Sign in</p>
        {error ? <p className="error-text">{error}</p> : null}
        <button type="button" onClick={handleOidcSignIn} disabled={isRedirecting}>
          {isRedirecting ? 'Redirecting…' : 'Continue with TaskHub ID'}
        </button>
        <button type="button" onClick={handleCreateAccount} disabled={isRedirecting}>
          Create account
        </button>
      </div>
    </div>
  )
}

function QuickAdd({
  token,
  projects,
  onTaskCreated,
  onProjectCreated,
  inline = false,
  className = '',
  autoFocusTitle = false,
}) {
  const [title, setTitle] = useState('')
  const [area, setArea] = useState('work')
  const [priorityLevel, setPriorityLevel] = useState('')
  const [dueDateInput, setDueDateInput] = useState('')
  const [recurrence, setRecurrence] = useState('none')
  const [projectQuery, setProjectQuery] = useState('')
  const [projectId, setProjectId] = useState('')
  const [projectMenuOpen, setProjectMenuOpen] = useState(false)
  const [projectSuggestions, setProjectSuggestions] = useState([])
  const [loadingProjectSuggestions, setLoadingProjectSuggestions] = useState(false)
  const [highlightedProjectIndex, setHighlightedProjectIndex] = useState(-1)
  const [creatingProject, setCreatingProject] = useState(false)
  const [error, setError] = useState('')
  const projectPickerRef = useRef(null)
  const projectInputRef = useRef(null)
  const projectSuggestionsRef = useRef(null)
  const [projectSuggestionsStyle, setProjectSuggestionsStyle] = useState(null)
  const [projectSuggestionsPlacement, setProjectSuggestionsPlacement] = useState('bottom')
  const areaProjects = useMemo(
    () => projects.filter((project) => project.area === area),
    [projects, area]
  )
  const normalizedQuery = projectQuery.trim().toLowerCase()
  const filteredProjects = useMemo(() => projectSuggestions.slice(0, 8), [projectSuggestions])
  const exactMatch = useMemo(
    () => projectSuggestions.find((project) => project.name.toLowerCase() === normalizedQuery),
    [projectSuggestions, normalizedQuery]
  )

  useEffect(() => {
    if (projectId && !areaProjects.some((project) => project.id === projectId)) {
      setProjectId('')
      setProjectQuery('')
    }
  }, [areaProjects, projectId])

  useEffect(() => {
    if (!projectMenuOpen || !filteredProjects.length) {
      setHighlightedProjectIndex(-1)
      return
    }
    if (highlightedProjectIndex >= filteredProjects.length) {
      setHighlightedProjectIndex(0)
    }
  }, [filteredProjects, projectMenuOpen, highlightedProjectIndex])

  useEffect(() => {
    if (!projectMenuOpen || !normalizedQuery) {
      setProjectSuggestions([])
      setLoadingProjectSuggestions(false)
      return
    }

    let active = true
    setLoadingProjectSuggestions(true)
    getProjects(token, { area, q: normalizedQuery, limit: 50 })
      .then((projectData) => {
        if (!active) {
          return
        }
        setProjectSuggestions(Array.isArray(projectData) ? projectData : [])
      })
      .catch(() => {
        if (!active) {
          return
        }
        setProjectSuggestions([])
      })
      .finally(() => {
        if (!active) {
          return
        }
        setLoadingProjectSuggestions(false)
      })

    return () => {
      active = false
    }
  }, [token, area, normalizedQuery, projectMenuOpen])

  useLayoutEffect(() => {
    if (!projectMenuOpen || !normalizedQuery) {
      setProjectSuggestionsStyle(null)
      setProjectSuggestionsPlacement('bottom')
      return
    }

    function updateProjectSuggestionsPosition() {
      if (!projectInputRef.current) {
        return
      }
      const rect = projectInputRef.current.getBoundingClientRect()
      const viewportPadding = 8
      const menuGap = 4
      const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - viewportPadding)
      const spaceAbove = Math.max(0, rect.top - viewportPadding)
      const placeAbove = spaceBelow < 180 && spaceAbove > spaceBelow
      const availableSpace = Math.max(0, (placeAbove ? spaceAbove : spaceBelow) - menuGap)
      const left = Math.max(viewportPadding, rect.left)
      const width = Math.max(160, Math.min(rect.width, window.innerWidth - left - viewportPadding))
      setProjectSuggestionsPlacement(placeAbove ? 'top' : 'bottom')
      setProjectSuggestionsStyle({
        left,
        top: placeAbove ? rect.top - menuGap : rect.bottom + menuGap,
        width,
        maxHeight: Math.max(120, Math.min(260, availableSpace)),
      })
    }

    updateProjectSuggestionsPosition()
    window.addEventListener('resize', updateProjectSuggestionsPosition)
    window.addEventListener('scroll', updateProjectSuggestionsPosition, true)
    return () => {
      window.removeEventListener('resize', updateProjectSuggestionsPosition)
      window.removeEventListener('scroll', updateProjectSuggestionsPosition, true)
    }
  }, [projectMenuOpen, normalizedQuery])

  useEffect(() => {
    function handleOutsideClick(event) {
      const clickedInsidePicker =
        projectPickerRef.current && projectPickerRef.current.contains(event.target)
      const clickedInsideSuggestions =
        projectSuggestionsRef.current && projectSuggestionsRef.current.contains(event.target)
      if (!clickedInsidePicker && !clickedInsideSuggestions) {
        setProjectMenuOpen(false)
        setHighlightedProjectIndex(-1)
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [])

  function selectProject(project) {
    setProjectId(project.id)
    setProjectQuery(project.name)
    setProjectMenuOpen(false)
    setHighlightedProjectIndex(-1)
    setError('')
  }

  async function createProjectFromQuery() {
    const name = projectQuery.trim()
    if (!name) {
      return
    }
    setCreatingProject(true)
    setError('')
    try {
      const created = await createProject(token, name, area)
      onProjectCreated(created)
      selectProject(created)
    } catch (e) {
      setError(e.message)
    } finally {
      setCreatingProject(false)
    }
  }

  function handleProjectInputChange(value) {
    setProjectQuery(value)
    setProjectMenuOpen(Boolean(value.trim()))
    setHighlightedProjectIndex(-1)
    const selected = areaProjects.find((project) => project.id === projectId)
    if (selected && selected.name !== value) {
      setProjectId('')
    }
  }

  function handleProjectInputKeyDown(event) {
    if (!projectMenuOpen || !filteredProjects.length) {
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlightedProjectIndex((current) => (current + 1) % filteredProjects.length)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlightedProjectIndex((current) =>
        current <= 0 ? filteredProjects.length - 1 : current - 1
      )
      return
    }
    if (event.key === 'Enter' && highlightedProjectIndex >= 0) {
      event.preventDefault()
      selectProject(filteredProjects[highlightedProjectIndex])
    }
  }

  async function submit(event) {
    event.preventDefault()
    if (!title.trim()) {
      return
    }
    if (recurrence !== 'none' && !dueDateInput) {
      setError('Recurring tasks require a date.')
      return
    }
    let resolvedProjectId = projectId
    if (!resolvedProjectId && projectQuery.trim()) {
      if (exactMatch) {
        resolvedProjectId = exactMatch.id
        setProjectId(exactMatch.id)
        setProjectQuery(exactMatch.name)
      } else {
        setError('Select a matching project or create one from the suggestions.')
        return
      }
    }

    setError('')
    try {
      await quickAddTask(
        token,
        title.trim(),
        area,
        resolvedProjectId,
        priorityValueFromLevel(priorityLevel),
        dueAtFromDateInput(dueDateInput),
        recurrence
      )
      setTitle('')
      setPriorityLevel('')
      setDueDateInput('')
      setRecurrence('none')
      onTaskCreated()
    } catch (e) {
      setError(e.message)
    }
  }

  const quickAddClassName = ['quick-add', inline ? 'quick-add-inline' : '', className]
    .filter(Boolean)
    .join(' ')
  const showProjectSuggestions = projectMenuOpen && normalizedQuery
  const projectSuggestionsMenu = showProjectSuggestions ? (
    <div
      ref={projectSuggestionsRef}
      className={
        projectSuggestionsPlacement === 'top'
          ? 'project-suggestions project-suggestions-portal project-suggestions-portal-top'
          : 'project-suggestions project-suggestions-portal'
      }
      style={projectSuggestionsStyle ?? undefined}
      role="listbox"
    >
      {filteredProjects.map((project, index) => (
        <button
          key={project.id}
          type="button"
          className={
            highlightedProjectIndex === index
              ? 'project-suggestion project-suggestion-highlighted'
              : 'project-suggestion'
          }
          onClick={() => selectProject(project)}
          onMouseEnter={() => setHighlightedProjectIndex(index)}
          aria-selected={highlightedProjectIndex === index}
        >
          {project.name}
        </button>
      ))}
      {!exactMatch && projectQuery.trim() ? (
        <button
          type="button"
          className="project-suggestion project-suggestion-create"
          onClick={createProjectFromQuery}
          disabled={creatingProject}
        >
          {creatingProject ? 'Creating...' : `Create "${projectQuery.trim()}"`}
        </button>
      ) : null}
      {!filteredProjects.length && loadingProjectSuggestions ? (
        <div className="project-suggestion project-suggestion-empty">Searching...</div>
      ) : null}
    </div>
  ) : null

  return (
    <form className={quickAddClassName} onSubmit={submit}>
      <input
        placeholder="Quick add task"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        aria-label="Quick add task"
        autoFocus={autoFocusTitle}
      />
      <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Area">
        <option value="work">Work</option>
        <option value="personal">Personal</option>
      </select>
      <select
        className={`quick-add-priority-select ${priorityClassFromLevel(priorityLevel)}`.trim()}
        value={priorityLevel}
        onChange={(e) => setPriorityLevel(e.target.value)}
        aria-label="Priority"
      >
        {PRIORITY_OPTIONS.map((option) => (
          <option key={option.value || 'none'} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <input
        type="date"
        value={dueDateInput}
        onChange={(e) => setDueDateInput(e.target.value)}
        aria-label="Task date"
      />
      <select value={recurrence} onChange={(e) => setRecurrence(e.target.value)} aria-label="Recurrence">
        {RECURRENCE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <div className="project-picker" ref={projectPickerRef}>
        <input
          ref={projectInputRef}
          value={projectQuery}
          onChange={(e) => handleProjectInputChange(e.target.value)}
          onFocus={() => setProjectMenuOpen(Boolean(projectQuery.trim()))}
          onKeyDown={handleProjectInputKeyDown}
          placeholder="Project (type to search or create)"
          aria-label="Project"
        />
      </div>
      {showProjectSuggestions
        ? typeof document === 'undefined'
          ? projectSuggestionsMenu
          : createPortal(projectSuggestionsMenu, document.body)
        : null}
      <button type="submit">Add</button>
      {error ? <span className="error-text">{error}</span> : null}
    </form>
  )
}

function SettingsPage({
  token,
  settingsDraft,
  settingsSavedMessage,
  isSavingSettings,
  isSyncingEmail,
  onUpdateSetting,
  onSaveSettings,
  onResetSettings,
  onConnectGoogle,
  onDisconnectGoogle,
  onSyncGoogle,
  onSyncImap,
  onBackToTasks,
}) {
  const [activeSection, setActiveSection] = useState('user')
  const [backupFile, setBackupFile] = useState(null)
  const [restoreConfirm, setRestoreConfirm] = useState('')
  const [backupStatus, setBackupStatus] = useState('')
  const [backupError, setBackupError] = useState('')
  const [isDownloadingBackup, setIsDownloadingBackup] = useState(false)
  const [isRestoringBackup, setIsRestoringBackup] = useState(false)
  const sections = [
    {
      id: 'user',
      label: 'User',
      description: 'Display name, reply-to email, and timezone defaults.',
    },
    {
      id: 'emailCapture',
      label: 'IMAP',
      description: 'Configure inbound IMAP account credentials and sync behavior.',
    },
    {
      id: 'ai',
      label: 'AI And Privacy',
      description: 'AI mode, cloud controls, and redaction preferences.',
    },
    {
      id: 'taskList',
      label: 'Task List',
      description: 'Default view and list behavior when opening tasks.',
    },
    {
      id: 'backupRestore',
      label: 'Backup & Restore',
      description: 'Download a database backup or restore from a backup file.',
    },
  ]
  const activeSectionMeta = sections.find((section) => section.id === activeSection) || sections[0]

  async function handleDownloadBackup() {
    setBackupError('')
    setBackupStatus('')
    setIsDownloadingBackup(true)
    try {
      const { blob, filename } = await downloadDatabaseBackup(token)
      const objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = filename
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      URL.revokeObjectURL(objectUrl)
      setBackupStatus(`Backup downloaded: ${filename}`)
    } catch (error) {
      setBackupError(error.message)
    } finally {
      setIsDownloadingBackup(false)
    }
  }

  async function handleRestoreBackup() {
    if (!backupFile) {
      setBackupError('Choose a backup file first.')
      return
    }
    if (restoreConfirm.trim().toUpperCase() !== 'RESTORE') {
      setBackupError('Type RESTORE to confirm before restoring.')
      return
    }

    setBackupError('')
    setBackupStatus('')
    setIsRestoringBackup(true)
    try {
      const response = await restoreDatabaseBackup(token, backupFile, 'RESTORE')
      setBackupStatus(response?.message || 'Database restore completed. Please sign in again.')
      setBackupFile(null)
      setRestoreConfirm('')
    } catch (error) {
      setBackupError(error.message)
    } finally {
      setIsRestoringBackup(false)
    }
  }

  function renderSectionContent() {
    if (activeSectionMeta.id === 'user') {
      return (
        <div className="settings-detail-card">
          <label className="settings-field" htmlFor="settings-display-name">
            <span>Display name</span>
            <input
              id="settings-display-name"
              value={settingsDraft.profile.displayName}
              onChange={(event) => onUpdateSetting('profile', 'displayName', event.target.value)}
              placeholder="Your name"
            />
          </label>
          <label className="settings-field" htmlFor="settings-reply-to-email">
            <span>Reply-to email</span>
            <input
              id="settings-reply-to-email"
              type="email"
              value={settingsDraft.profile.replyToEmail}
              onChange={(event) => onUpdateSetting('profile', 'replyToEmail', event.target.value)}
              placeholder="name@example.com"
            />
          </label>
          <label className="settings-field" htmlFor="settings-timezone">
            <span>Time zone</span>
            <input
              id="settings-timezone"
              value={settingsDraft.profile.timezone}
              onChange={(event) => onUpdateSetting('profile', 'timezone', event.target.value)}
              placeholder="UTC"
            />
          </label>
        </div>
      )
    }

    if (activeSectionMeta.id === 'emailCapture') {
      const inboundMode = settingsDraft.emailCapture.provider
      const inboundModeLabel =
        inboundMode === 'imap' ? 'IMAP' : inboundMode === 'gmail_oauth' ? 'Gmail OAuth' : 'Webhook'
      return (
        <div className="settings-detail-card">
          <label className="settings-field" htmlFor="settings-inbound-provider">
            <span>Current incoming mode</span>
            <input id="settings-inbound-provider" value={inboundModeLabel} readOnly />
          </label>
          {inboundMode === 'gmail_oauth' && settingsDraft.emailCapture.oauthConnected ? (
            <label className="settings-field" htmlFor="settings-gmail-account">
              <span>Connected Gmail account</span>
              <input id="settings-gmail-account" value={settingsDraft.emailCapture.oauthEmail} readOnly />
            </label>
          ) : null}
          {inboundMode === 'gmail_oauth' ? (
            <div className="settings-field-row">
              <button type="button" onClick={onConnectGoogle} disabled={isSavingSettings || isSyncingEmail}>
                Connect Gmail (OAuth)
              </button>
              <button
                type="button"
                onClick={onDisconnectGoogle}
                disabled={!settingsDraft.emailCapture.oauthConnected || isSavingSettings || isSyncingEmail}
              >
                Disconnect Gmail
              </button>
              <button
                type="button"
                onClick={onSyncGoogle}
                disabled={!settingsDraft.emailCapture.oauthConnected || isSavingSettings || isSyncingEmail}
              >
                {isSyncingEmail ? 'Syncing...' : 'Sync Gmail Now'}
              </button>
            </div>
          ) : null}
          {inboundMode === 'imap' ? (
            <div className="settings-field-row">
              <button
                type="button"
                onClick={onSyncImap}
                disabled={!settingsDraft.emailCapture.imapConfigured || isSavingSettings || isSyncingEmail}
              >
                {isSyncingEmail ? 'Syncing...' : 'Sync IMAP Now'}
              </button>
            </div>
          ) : null}
          {inboundMode === 'imap' ? (
            <>
              <label className="settings-field" htmlFor="settings-imap-username">
                <span>IMAP username</span>
                <input
                  id="settings-imap-username"
                  value={settingsDraft.emailCapture.imapUsername}
                  onChange={(event) => onUpdateSetting('emailCapture', 'imapUsername', event.target.value)}
                  placeholder="you@example.com"
                />
              </label>
              <label className="settings-field" htmlFor="settings-imap-password">
                <span>IMAP password</span>
                <input
                  id="settings-imap-password"
                  type="password"
                  value={settingsDraft.emailCapture.imapPasswordInput}
                  onChange={(event) => onUpdateSetting('emailCapture', 'imapPasswordInput', event.target.value)}
                  placeholder={
                    settingsDraft.emailCapture.imapConfigured
                      ? 'Leave blank to keep current password'
                      : 'Enter app password'
                  }
                />
              </label>
              <label className="settings-checkbox" htmlFor="settings-imap-clear-password">
                <input
                  id="settings-imap-clear-password"
                  type="checkbox"
                  checked={settingsDraft.emailCapture.imapClearPassword}
                  onChange={(event) => onUpdateSetting('emailCapture', 'imapClearPassword', event.target.checked)}
                />
                <span>Clear stored IMAP password on save</span>
              </label>
              <label className="settings-field" htmlFor="settings-imap-provider">
                <span>IMAP provider</span>
                <select
                  id="settings-imap-provider"
                  value={settingsDraft.emailCapture.imapProvider}
                  onChange={(event) => onUpdateSetting('emailCapture', 'imapProvider', event.target.value)}
                >
                  <option value="auto">Auto detect</option>
                  <option value="gmail">Gmail</option>
                  <option value="outlook">Outlook / Office 365</option>
                  <option value="yahoo">Yahoo</option>
                  <option value="icloud">iCloud</option>
                  <option value="aol">AOL</option>
                  <option value="fastmail">Fastmail</option>
                </select>
              </label>
              <label className="settings-field" htmlFor="settings-imap-host">
                <span>IMAP host (optional)</span>
                <input
                  id="settings-imap-host"
                  value={settingsDraft.emailCapture.imapHost}
                  onChange={(event) => onUpdateSetting('emailCapture', 'imapHost', event.target.value)}
                  placeholder="imap.example.com"
                />
              </label>
              <label className="settings-field" htmlFor="settings-imap-port">
                <span>IMAP port</span>
                <input
                  id="settings-imap-port"
                  type="number"
                  min="1"
                  max="65535"
                  value={settingsDraft.emailCapture.imapPort}
                  onChange={(event) => onUpdateSetting('emailCapture', 'imapPort', event.target.value)}
                  placeholder="993"
                />
              </label>
              <label className="settings-checkbox" htmlFor="settings-imap-use-ssl">
                <input
                  id="settings-imap-use-ssl"
                  type="checkbox"
                  checked={settingsDraft.emailCapture.imapUseSsl}
                  onChange={(event) => onUpdateSetting('emailCapture', 'imapUseSsl', event.target.checked)}
                />
                <span>Use SSL/TLS</span>
              </label>
              <label className="settings-field" htmlFor="settings-imap-folder">
                <span>IMAP folder</span>
                <input
                  id="settings-imap-folder"
                  value={settingsDraft.emailCapture.imapFolder}
                  onChange={(event) => onUpdateSetting('emailCapture', 'imapFolder', event.target.value)}
                  placeholder="INBOX"
                />
              </label>
              <label className="settings-field" htmlFor="settings-imap-search-criteria">
                <span>IMAP search criteria</span>
                <input
                  id="settings-imap-search-criteria"
                  value={settingsDraft.emailCapture.imapSearchCriteria}
                  onChange={(event) => onUpdateSetting('emailCapture', 'imapSearchCriteria', event.target.value)}
                  placeholder="UNSEEN"
                />
              </label>
              <label className="settings-checkbox" htmlFor="settings-imap-mark-seen">
                <input
                  id="settings-imap-mark-seen"
                  type="checkbox"
                  checked={settingsDraft.emailCapture.imapMarkSeenOnSuccess}
                  onChange={(event) =>
                    onUpdateSetting('emailCapture', 'imapMarkSeenOnSuccess', event.target.checked)
                  }
                />
                <span>Mark message as seen when imported</span>
              </label>
            </>
          ) : null}
          <label className="settings-field" htmlFor="settings-inbound-email-address">
            <span>Inbound task email address</span>
            <input
              id="settings-inbound-email-address"
              type="email"
              value={settingsDraft.emailCapture.inboundAddress}
              onChange={(event) =>
                onUpdateSetting('emailCapture', 'inboundAddress', event.target.value)
              }
              placeholder="tasks@yourdomain.com"
            />
          </label>
          <label className="settings-field" htmlFor="settings-inbound-ingest-token">
            <span>Inbound ingest token</span>
            <input
              id="settings-inbound-ingest-token"
              value={settingsDraft.emailCapture.inboundToken}
              readOnly
              placeholder="Generated after Save Settings"
            />
          </label>
          <label className="settings-checkbox" htmlFor="settings-inbound-rotate-token">
            <input
              id="settings-inbound-rotate-token"
              type="checkbox"
              checked={settingsDraft.emailCapture.rotateToken}
              onChange={(event) =>
                onUpdateSetting('emailCapture', 'rotateToken', event.target.checked)
              }
            />
            <span>Rotate ingest token on save</span>
          </label>
          <label className="settings-field" htmlFor="settings-inbound-whitelist">
            <span>Sender whitelist (one email per line)</span>
            <textarea
              id="settings-inbound-whitelist"
              className="settings-textarea"
              value={settingsDraft.emailCapture.whitelistInput}
              onChange={(event) =>
                onUpdateSetting('emailCapture', 'whitelistInput', event.target.value)
              }
              placeholder={'alice@example.com\nbob@example.com'}
            />
          </label>
          {inboundMode === 'webhook' ? (
            <>
              <label className="settings-field" htmlFor="settings-inbound-webhook-path">
                <span>Inbound webhook path</span>
                <input id="settings-inbound-webhook-path" value="/capture/email/inbound" readOnly />
              </label>
              <p className="settings-note">
                Configure your mail provider to POST forwarded <code>.eml</code> files to this path with
                header <code>X-TaskHub-Ingest-Token</code>. The forwarded body should use:
                title, project, work/personal, priority (one per line).
              </p>
              <p className="settings-note">
                Outlook add-in users should use this webhook path, then paste this recipient + ingest token in
                the add-in Advanced Settings.
              </p>
            </>
          ) : null}
          {inboundMode === 'imap' ? (
            <p className="settings-note">
              Enter credentials here. Host is optional and will auto-detect from provider or username domain.
              Current configuration: {settingsDraft.emailCapture.imapConfigured ? 'ready' : 'incomplete'}.
            </p>
          ) : null}
          {inboundMode === 'gmail_oauth' ? (
            <p className="settings-note">
            Gmail OAuth mode reads unread inbox email directly from Google and imports matching messages.
            </p>
          ) : null}
          <p className="settings-note">
            When whitelist entries are set, only those sender addresses can create tasks. Leave blank to
            allow all senders.
          </p>
          <p className="settings-note">
            Rotate the ingest token after any suspected exposure. The new token is only shown immediately
            after rotation, so copy it to your add-in configuration right away.
          </p>
        </div>
      )
    }

    if (activeSectionMeta.id === 'ai') {
      return (
        <div className="settings-detail-card">
          <label className="settings-field" htmlFor="settings-ai-mode">
            <span>AI mode</span>
            <select
              id="settings-ai-mode"
              value={settingsDraft.ai.mode}
              onChange={(event) => onUpdateSetting('ai', 'mode', event.target.value)}
            >
              <option value="off">Off</option>
              <option value="local">Local</option>
              <option value="cloud">Cloud</option>
              <option value="hybrid">Hybrid</option>
            </select>
          </label>
          <label className="settings-checkbox" htmlFor="settings-ai-allow-cloud">
            <input
              id="settings-ai-allow-cloud"
              type="checkbox"
              checked={settingsDraft.ai.allowCloudAi}
              onChange={(event) => onUpdateSetting('ai', 'allowCloudAi', event.target.checked)}
            />
            <span>Allow cloud AI requests</span>
          </label>
          <label className="settings-checkbox" htmlFor="settings-ai-redact-sensitive">
            <input
              id="settings-ai-redact-sensitive"
              type="checkbox"
              checked={settingsDraft.ai.redactSensitivePatterns}
              onChange={(event) => onUpdateSetting('ai', 'redactSensitivePatterns', event.target.checked)}
            />
            <span>Redact sensitive patterns before AI processing</span>
          </label>
          <label className="settings-field" htmlFor="settings-ai-local-url">
            <span>Local AI base URL</span>
            <input
              id="settings-ai-local-url"
              value={settingsDraft.ai.localBaseUrl}
              onChange={(event) => onUpdateSetting('ai', 'localBaseUrl', event.target.value)}
              placeholder="http://local-ai:8000"
            />
          </label>
        </div>
      )
    }

    if (activeSectionMeta.id === 'backupRestore') {
      return (
        <div className="settings-detail-card">
          <div className="settings-backup-block">
            <h3>Create Backup</h3>
            <p className="settings-backup-text">
              Download the current database as a JSON backup fixture file.
            </p>
            <button type="button" onClick={handleDownloadBackup} disabled={isDownloadingBackup}>
              {isDownloadingBackup ? 'Preparing Backup...' : 'Download Backup'}
            </button>
          </div>
          <div className="settings-backup-block">
            <h3>Restore Database</h3>
            <p className="settings-backup-warning">
              Warning: restoring will replace the current database contents.
            </p>
            <label className="settings-field" htmlFor="settings-backup-file">
              <span>Backup file</span>
              <input
                id="settings-backup-file"
                type="file"
                accept="application/json,.json"
                onChange={(event) => setBackupFile(event.target.files?.[0] || null)}
              />
            </label>
            <label className="settings-field" htmlFor="settings-restore-confirm">
              <span>Type RESTORE to confirm</span>
              <input
                id="settings-restore-confirm"
                value={restoreConfirm}
                onChange={(event) => setRestoreConfirm(event.target.value)}
                placeholder="RESTORE"
              />
            </label>
            <button
              type="button"
              className="settings-restore-button"
              onClick={handleRestoreBackup}
              disabled={isRestoringBackup}
            >
              {isRestoringBackup ? 'Restoring...' : 'Restore Database'}
            </button>
          </div>
          {backupStatus ? <p className="settings-backup-success">{backupStatus}</p> : null}
          {backupError ? <p className="settings-backup-error">{backupError}</p> : null}
        </div>
      )
    }

    return (
      <div className="settings-detail-card">
        <label className="settings-field" htmlFor="settings-default-area">
          <span>Default area view</span>
          <select
            id="settings-default-area"
            value={settingsDraft.taskList.defaultArea}
            onChange={(event) => onUpdateSetting('taskList', 'defaultArea', event.target.value)}
          >
            <option value="all">All Tasks</option>
            <option value="work">Work</option>
            <option value="personal">Personal</option>
          </select>
        </label>
        <label className="settings-checkbox" htmlFor="settings-default-group-priority">
          <input
            id="settings-default-group-priority"
            type="checkbox"
            checked={settingsDraft.taskList.groupByPriorityDefault}
            onChange={(event) => onUpdateSetting('taskList', 'groupByPriorityDefault', event.target.checked)}
          />
          <span>Default to grouped-by-priority task list</span>
        </label>
        <label className="settings-checkbox" htmlFor="settings-area-text-coloring-enabled">
          <input
            id="settings-area-text-coloring-enabled"
            type="checkbox"
            checked={settingsDraft.taskList.areaTextColoringEnabled}
            onChange={(event) =>
              onUpdateSetting('taskList', 'areaTextColoringEnabled', event.target.checked)
            }
          />
          <span>Color task text by area in the main list</span>
        </label>
        <div className="settings-color-grid">
          <label className="settings-field" htmlFor="settings-work-text-color">
            <span>Work text color</span>
            <input
              id="settings-work-text-color"
              type="color"
              value={settingsDraft.taskList.workTextColor}
              disabled={!settingsDraft.taskList.areaTextColoringEnabled}
              onChange={(event) => onUpdateSetting('taskList', 'workTextColor', event.target.value)}
            />
          </label>
          <label className="settings-field" htmlFor="settings-personal-text-color">
            <span>Personal text color</span>
            <input
              id="settings-personal-text-color"
              type="color"
              value={settingsDraft.taskList.personalTextColor}
              disabled={!settingsDraft.taskList.areaTextColoringEnabled}
              onChange={(event) => onUpdateSetting('taskList', 'personalTextColor', event.target.value)}
            />
          </label>
        </div>
      </div>
    )
  }

  return (
    <section className="settings-page">
      <div className="settings-header">
        <div>
          <h1>Settings</h1>
          <p>Configure user profile, incoming email capture, AI/privacy, and task list defaults.</p>
        </div>
        <button type="button" onClick={onBackToTasks}>
          Back To Tasks
        </button>
      </div>
      <form className="settings-form" onSubmit={onSaveSettings}>
        <label className="settings-mobile-section" htmlFor="settings-mobile-section">
          <span>Section</span>
          <select
            id="settings-mobile-section"
            value={activeSectionMeta.id}
            onChange={(event) => setActiveSection(event.target.value)}
          >
            {sections.map((section) => (
              <option key={section.id} value={section.id}>
                {section.label}
              </option>
            ))}
          </select>
        </label>
        <div className="settings-layout">
          <aside className="settings-nav-sidebar" aria-label="Settings sections">
            <p className="settings-nav-title">Sections</p>
            <div className="settings-nav-list">
              {sections.map((section) => (
                <button
                  key={section.id}
                  type="button"
                  className={
                    activeSectionMeta.id === section.id
                      ? 'settings-nav-button settings-nav-button-active'
                      : 'settings-nav-button'
                  }
                  onClick={() => setActiveSection(section.id)}
                >
                  <span className="settings-nav-button-label">{section.label}</span>
                  <span className="settings-nav-button-description">{section.description}</span>
                </button>
              ))}
            </div>
          </aside>
          <section className="settings-detail-panel">
            <header className="settings-detail-header">
              <h2>{activeSectionMeta.label}</h2>
              <p>{activeSectionMeta.description}</p>
            </header>
            {renderSectionContent()}
          </section>
        </div>
        <div className="settings-actions">
          <button type="submit" disabled={isSavingSettings}>
            {isSavingSettings ? 'Saving...' : 'Save Settings'}
          </button>
          <button type="button" className="settings-reset" onClick={onResetSettings} disabled={isSavingSettings}>
            Reset To Defaults
          </button>
          <p className="settings-note">
            Incoming email settings are stored on the backend organization. Profile and list preferences
            remain per-browser. Backup/restore runs against the backend database.
          </p>
        </div>
        {settingsSavedMessage ? <p className="settings-saved-message">{settingsSavedMessage}</p> : null}
      </form>
    </section>
  )
}

function Dashboard({ token, onLogout }) {
  const navigate = useNavigate()
  const location = useLocation()
  const initialSettings = useMemo(() => loadAppSettings(), [])
  const isSettingsView = location.pathname === '/settings'
  const [tasks, setTasks] = useState([])
  const [taskTotal, setTaskTotal] = useState(0)
  const [projects, setProjects] = useState([])
  const [sidebarProjects, setSidebarProjects] = useState([])
  const [activeView, setActiveView] = useState(() => initialTaskViewFromSettings(initialSettings))
  const [groupByPriority, setGroupByPriority] = useState(
    () => initialSettings.taskList.groupByPriorityDefault
  )
  const [areaTextColoringEnabled, setAreaTextColoringEnabled] = useState(
    () => initialSettings.taskList.areaTextColoringEnabled
  )
  const [areaTextColors, setAreaTextColors] = useState(() => ({
    work: normalizeHexColor(
      initialSettings.taskList.workTextColor,
      DEFAULT_APP_SETTINGS.taskList.workTextColor
    ),
    personal: normalizeHexColor(
      initialSettings.taskList.personalTextColor,
      DEFAULT_APP_SETTINGS.taskList.personalTextColor
    ),
  }))
  const [includeHistory, setIncludeHistory] = useState(false)
  const [settingsDraft, setSettingsDraft] = useState(initialSettings)
  const [settingsSavedMessage, setSettingsSavedMessage] = useState('')
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [isSyncingEmail, setIsSyncingEmail] = useState(false)
  const [error, setError] = useState('')
  const [reloadCounter, setReloadCounter] = useState(0)
  const [updatingTaskIds, setUpdatingTaskIds] = useState(new Set())
  const [deletingTaskIds, setDeletingTaskIds] = useState(new Set())
  const [openDeleteTaskId, setOpenDeleteTaskId] = useState('')
  const [draggedTaskId, setDraggedTaskId] = useState('')
  const [dropTarget, setDropTarget] = useState(null)
  const [expandedTaskId, setExpandedTaskId] = useState('')
  const [detailsNotes, setDetailsNotes] = useState('')
  const [detailsDueDate, setDetailsDueDate] = useState('')
  const [detailsRecurrence, setDetailsRecurrence] = useState('none')
  const [detailsAttachments, setDetailsAttachments] = useState([])
  const [isAttachmentDragOver, setIsAttachmentDragOver] = useState(false)
  const [attachmentPreview, setAttachmentPreview] = useState(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [isMobileQuickAddOpen, setIsMobileQuickAddOpen] = useState(false)
  const [isDesktopQuickAddOpen, setIsDesktopQuickAddOpen] = useState(false)
  const [taskSort, setTaskSort] = useState({ key: '', direction: 'asc' })
  const projectNameById = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project.name])),
    [projects]
  )

  const workProjects = useMemo(
    () => sidebarProjects.filter((project) => project.area === 'work'),
    [sidebarProjects]
  )
  const personalProjects = useMemo(
    () => sidebarProjects.filter((project) => project.area === 'personal'),
    [sidebarProjects]
  )
  const filteredTasks = useMemo(() => {
    if (!taskSort.key) {
      return tasks
    }

    const direction = taskSort.direction === 'desc' ? -1 : 1
    return [...tasks].sort((leftTask, rightTask) => {
      let result = 0
      if (taskSort.key === 'title') {
        result = compareTaskTextValues(leftTask.title, rightTask.title)
      } else if (taskSort.key === 'area') {
        result = compareTaskTextValues(formatAreaLabel(leftTask.area), formatAreaLabel(rightTask.area))
      } else if (taskSort.key === 'project') {
        const leftProjectName = leftTask.project ? projectNameById[leftTask.project] || 'Unknown project' : ''
        const rightProjectName = rightTask.project
          ? projectNameById[rightTask.project] || 'Unknown project'
          : ''
        result = compareTaskTextValues(leftProjectName, rightProjectName)
      } else if (taskSort.key === 'priority') {
        result = compareTaskPriorityValues(leftTask.priority, rightTask.priority, direction)
      } else if (taskSort.key === 'date') {
        result = compareTaskDateValues(leftTask.due_at, rightTask.due_at, direction)
      } else if (taskSort.key === 'created') {
        result = compareTaskDateValues(
          leftTask.created_at || leftTask.created,
          rightTask.created_at || rightTask.created,
          direction
        )
      }
      if (taskSort.key === 'priority' || taskSort.key === 'date' || taskSort.key === 'created') {
        return result
      }
      return result * direction
    })
  }, [projectNameById, taskSort.direction, taskSort.key, tasks])
  const isManualTaskOrder = !taskSort.key
  const activeViewLabel = useMemo(() => {
    if (activeView.type === 'all') {
      return 'All Tasks'
    }
    if (activeView.type === 'area') {
      return activeView.area === 'work' ? 'Work' : 'Personal'
    }
    if (activeView.type === 'project') {
      return projectNameById[activeView.projectId] || 'Project'
    }
    return 'All Tasks'
  }, [activeView, projectNameById])
  const taskCountLabel = useMemo(() => `${taskTotal} tasks`, [taskTotal])
  const taskQueryParams = useMemo(() => {
    const params = {}
    if (activeView.type === 'area') {
      params.area = activeView.area
    }
    if (activeView.type === 'project') {
      params.project_id = activeView.projectId
    }
    if (groupByPriority) {
      params.sort_mode = 'priority_manual'
    }
    if (includeHistory) {
      params.include_history = 'true'
    }
    return params
  }, [activeView, groupByPriority, includeHistory])

  useEffect(() => {
    if (activeView.type !== 'project') {
      return
    }
    if (!sidebarProjects.some((project) => project.id === activeView.projectId)) {
      setActiveView({ type: 'all' })
    }
  }, [activeView, sidebarProjects])

  useEffect(() => {
    if (!openDeleteTaskId) {
      return undefined
    }

    function handleOutsideClick(event) {
      const actionCell = event.target.closest(`[data-task-action-id="${openDeleteTaskId}"]`)
      if (!actionCell) {
        setOpenDeleteTaskId('')
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [openDeleteTaskId])

  useEffect(() => {
    setDraggedTaskId('')
    setDropTarget(null)
  }, [taskSort.direction, taskSort.key])

  useEffect(() => {
    if (!expandedTaskId) {
      return
    }
    if (!tasks.some((task) => task.id === expandedTaskId)) {
      setExpandedTaskId('')
      setDetailsNotes('')
      setDetailsDueDate('')
      setDetailsRecurrence('none')
      setDetailsAttachments([])
      setIsAttachmentDragOver(false)
      setAttachmentPreview(null)
    }
  }, [expandedTaskId, tasks])

  useEffect(() => {
    if (!attachmentPreview) {
      return undefined
    }

    function handleEscape(event) {
      if (event.key === 'Escape') {
        setAttachmentPreview(null)
      }
    }

    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('keydown', handleEscape)
    }
  }, [attachmentPreview])

  useEffect(() => {
    if (!isDesktopQuickAddOpen) {
      return undefined
    }

    function handleEscape(event) {
      if (event.key === 'Escape') {
        setIsDesktopQuickAddOpen(false)
      }
    }

    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('keydown', handleEscape)
    }
  }, [isDesktopQuickAddOpen])

  useEffect(() => {
    setIsSidebarOpen(false)
    setIsMobileQuickAddOpen(false)
    setIsDesktopQuickAddOpen(false)
  }, [location.pathname])

  useEffect(() => {
    let active = true
    getProjects(token)
      .then((projectData) => {
        if (!active) return
        setProjects(Array.isArray(projectData) ? projectData : [])
        setError('')
      })
      .catch((e) => {
        if (!active) return
        setError(e.message)
      })

    return () => {
      active = false
    }
  }, [token, reloadCounter])

  useEffect(() => {
    let active = true
    getProjects(token, { has_tasks: true })
      .then((projectData) => {
        if (!active) return
        setSidebarProjects(Array.isArray(projectData) ? projectData : [])
        setError('')
      })
      .catch((e) => {
        if (!active) return
        setError(e.message)
      })

    return () => {
      active = false
    }
  }, [token, reloadCounter])

  useEffect(() => {
    let active = true
    getEmailCaptureSettings(token)
      .then((emailCaptureData) => {
        if (!active) return
        setSettingsDraft((current) => ({
          ...current,
          emailCapture: emailCaptureSettingsFromApi(emailCaptureData),
        }))
      })
      .catch((e) => {
        if (!active) return
        setSettingsSavedMessage(`Could not load incoming email settings: ${e.message}`)
      })

    return () => {
      active = false
    }
  }, [token])

  useEffect(() => {
    if (!isSettingsView) {
      return
    }
    const params = new URLSearchParams(location.search)
    const code = (params.get('code') || '').trim()
    const state = (params.get('state') || '').trim()
    if (!code || !state) {
      return
    }

    let active = true
    setIsSavingSettings(true)
    setSettingsSavedMessage('Completing Gmail OAuth...')

    exchangeGoogleEmailOAuthCode(token, code, state)
      .then((emailCaptureData) => {
        if (!active) return
        setSettingsDraft((current) => ({
          ...current,
          emailCapture: emailCaptureSettingsFromApi(emailCaptureData),
        }))
        setSettingsSavedMessage('Gmail OAuth connected.')
        navigate('/settings', { replace: true })
      })
      .catch((e) => {
        if (!active) return
        setSettingsSavedMessage(`Gmail OAuth failed: ${e.message}`)
        navigate('/settings', { replace: true })
      })
      .finally(() => {
        if (!active) return
        setIsSavingSettings(false)
      })

    return () => {
      active = false
    }
  }, [isSettingsView, location.search, navigate, token])

  useEffect(() => {
    if (isSettingsView) {
      return undefined
    }
    let active = true
    getTasks(token, taskQueryParams)
      .then((taskData) => {
        if (!active) return
        const results = Array.isArray(taskData?.results) ? taskData.results : []
        setTasks(results)
        setTaskTotal(typeof taskData?.total === 'number' ? taskData.total : results.length)
        setError('')
      })
      .catch((e) => {
        if (!active) return
        setError(e.message)
      })

    return () => {
      active = false
    }
  }, [token, taskQueryParams, reloadCounter, isSettingsView])

  useEffect(() => {
    let active = true
    let cursor = ''
    let currentController = null
    let retryTimer = null

    async function runLiveSyncLoop() {
      while (active) {
        currentController = new AbortController()
        try {
          const response = await waitForTaskChanges(token, {
            cursor,
            timeoutSeconds: LIVE_SYNC_TIMEOUT_SECONDS,
            pollIntervalMs: LIVE_SYNC_POLL_INTERVAL_MS,
            signal: currentController.signal,
          })
          if (!active) {
            return
          }
          if (typeof response?.cursor === 'string' && response.cursor) {
            cursor = response.cursor
          }
          if (response?.changed) {
            setReloadCounter((value) => value + 1)
          }
        } catch (e) {
          if (!active || e?.name === 'AbortError') {
            return
          }
          await new Promise((resolve) => {
            retryTimer = window.setTimeout(resolve, LIVE_SYNC_RETRY_DELAY_MS)
          })
        } finally {
          currentController = null
        }
      }
    }

    runLiveSyncLoop()
    return () => {
      active = false
      if (currentController) {
        currentController.abort()
      }
      if (retryTimer) {
        window.clearTimeout(retryTimer)
      }
    }
  }, [token])

  function handleTaskCreated() {
    setReloadCounter((value) => value + 1)
    setIsMobileQuickAddOpen(false)
    setIsDesktopQuickAddOpen(false)
  }

  function handleProjectCreated(project) {
    setProjects((current) => {
      if (current.some((existing) => existing.id === project.id)) {
        return current
      }
      return [...current, project]
    })
  }

  function openTaskView(nextView) {
    setActiveView(nextView)
    setIsSidebarOpen(false)
    setIsMobileQuickAddOpen(false)
    setIsDesktopQuickAddOpen(false)
    if (isSettingsView) {
      navigate('/tasks')
    }
  }

  function openSettingsView() {
    setIsSidebarOpen(false)
    setIsMobileQuickAddOpen(false)
    setIsDesktopQuickAddOpen(false)
    navigate('/settings')
  }

  function handleUpdateSetting(section, key, value) {
    setSettingsSavedMessage('')
    setSettingsDraft((current) => ({
      ...current,
      [section]: {
        ...current[section],
        [key]: value,
      },
    }))
  }

  async function handleSaveSettings(event) {
    event.preventDefault()

    setIsSavingSettings(true)
    setSettingsSavedMessage('')

    const localSettings = {
      ...settingsDraft,
      emailCapture: {
        ...settingsDraft.emailCapture,
        rotateToken: false,
      },
    }

    let nextSettings = localSettings
    let saveMessage = 'Settings saved.'

    try {
      try {
        const emailCaptureData = await updateEmailCaptureSettings(token, {
          inboundEmailAddress: settingsDraft.emailCapture.inboundAddress.trim(),
          inboundEmailWhitelist: parseEmailWhitelistInput(settingsDraft.emailCapture.whitelistInput),
          rotateToken: settingsDraft.emailCapture.rotateToken,
          imapUsername: settingsDraft.emailCapture.imapUsername.trim(),
          imapPassword: settingsDraft.emailCapture.imapPasswordInput,
          imapClearPassword: settingsDraft.emailCapture.imapClearPassword,
          imapHost: settingsDraft.emailCapture.imapHost.trim(),
          imapProvider: settingsDraft.emailCapture.imapProvider,
          imapPort: Number(settingsDraft.emailCapture.imapPort || 993),
          imapUseSsl: settingsDraft.emailCapture.imapUseSsl,
          imapFolder: settingsDraft.emailCapture.imapFolder.trim(),
          imapSearchCriteria: settingsDraft.emailCapture.imapSearchCriteria.trim(),
          imapMarkSeenOnSuccess: settingsDraft.emailCapture.imapMarkSeenOnSuccess,
        })
        nextSettings = {
          ...localSettings,
          emailCapture: emailCaptureSettingsFromApi(emailCaptureData),
        }
      } catch (e) {
        saveMessage = `Local settings saved. Incoming email settings were not saved: ${e.message}`
      }

      setSettingsDraft(nextSettings)
      saveAppSettings(nextSettings)
      setSettingsSavedMessage(saveMessage)
      setGroupByPriority(Boolean(nextSettings.taskList.groupByPriorityDefault))
      setAreaTextColoringEnabled(Boolean(nextSettings.taskList.areaTextColoringEnabled))
      setAreaTextColors({
        work: normalizeHexColor(
          nextSettings.taskList.workTextColor,
          DEFAULT_APP_SETTINGS.taskList.workTextColor
        ),
        personal: normalizeHexColor(
          nextSettings.taskList.personalTextColor,
          DEFAULT_APP_SETTINGS.taskList.personalTextColor
        ),
      })
      if (nextSettings.taskList.defaultArea === 'work') {
        setActiveView({ type: 'area', area: 'work' })
      } else if (nextSettings.taskList.defaultArea === 'personal') {
        setActiveView({ type: 'area', area: 'personal' })
      } else {
        setActiveView({ type: 'all' })
      }
    } finally {
      setIsSavingSettings(false)
    }
  }

  function handleResetSettings() {
    const reset = cloneDefaultAppSettings()
    reset.emailCapture = {
      inboundAddress: settingsDraft.emailCapture.inboundAddress,
      inboundToken: settingsDraft.emailCapture.inboundToken,
      whitelistInput: settingsDraft.emailCapture.whitelistInput,
      provider: settingsDraft.emailCapture.provider,
      oauthEmail: settingsDraft.emailCapture.oauthEmail,
      oauthConnected: settingsDraft.emailCapture.oauthConnected,
      imapConfigured: settingsDraft.emailCapture.imapConfigured,
      imapUsername: settingsDraft.emailCapture.imapUsername,
      imapPasswordInput: '',
      imapClearPassword: false,
      imapHost: settingsDraft.emailCapture.imapHost,
      imapProvider: settingsDraft.emailCapture.imapProvider,
      imapPort: settingsDraft.emailCapture.imapPort,
      imapUseSsl: settingsDraft.emailCapture.imapUseSsl,
      imapFolder: settingsDraft.emailCapture.imapFolder,
      imapSearchCriteria: settingsDraft.emailCapture.imapSearchCriteria,
      imapMarkSeenOnSuccess: settingsDraft.emailCapture.imapMarkSeenOnSuccess,
      rotateToken: false,
    }
    setSettingsDraft(reset)
    saveAppSettings(reset)
    setSettingsSavedMessage('Local settings reset to defaults. Incoming email settings were preserved.')
    setGroupByPriority(Boolean(reset.taskList.groupByPriorityDefault))
    setAreaTextColoringEnabled(Boolean(reset.taskList.areaTextColoringEnabled))
    setAreaTextColors({
      work: normalizeHexColor(reset.taskList.workTextColor, DEFAULT_APP_SETTINGS.taskList.workTextColor),
      personal: normalizeHexColor(
        reset.taskList.personalTextColor,
        DEFAULT_APP_SETTINGS.taskList.personalTextColor
      ),
    })
    setActiveView({ type: 'all' })
  }

  async function handleToggleComplete(task, completed) {
    setError('')
    setUpdatingTaskIds((current) => {
      const next = new Set(current)
      next.add(task.id)
      return next
    })

    try {
      await setTaskCompleted(token, task.id, completed)
      setReloadCounter((value) => value + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setUpdatingTaskIds((current) => {
        const next = new Set(current)
        next.delete(task.id)
        return next
      })
    }
  }

  function toggleDeleteReveal(taskId) {
    setOpenDeleteTaskId((current) => (current === taskId ? '' : taskId))
  }

  async function handleDeleteTask(taskId) {
    setError('')
    setDeletingTaskIds((current) => {
      const next = new Set(current)
      next.add(taskId)
      return next
    })
    try {
      await deleteTask(token, taskId)
      setOpenDeleteTaskId('')
      setReloadCounter((value) => value + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setDeletingTaskIds((current) => {
        const next = new Set(current)
        next.delete(taskId)
        return next
      })
    }
  }

  async function handleConnectGoogleOAuth() {
    setSettingsSavedMessage('')
    setIsSavingSettings(true)
    try {
      const data = await initiateGoogleEmailOAuth(token)
      const authUrl = String(data?.auth_url || '')
      if (!authUrl) {
        throw new Error('OAuth authorization URL was not returned')
      }
      window.location.assign(authUrl)
    } catch (e) {
      setSettingsSavedMessage(`Could not start Gmail OAuth: ${e.message}`)
      setIsSavingSettings(false)
    }
  }

  async function handleDisconnectGoogleOAuth() {
    setSettingsSavedMessage('')
    setIsSavingSettings(true)
    try {
      const data = await disconnectGoogleEmailOAuth(token)
      setSettingsDraft((current) => ({
        ...current,
        emailCapture: emailCaptureSettingsFromApi(data),
      }))
      setSettingsSavedMessage('Gmail OAuth disconnected.')
    } catch (e) {
      setSettingsSavedMessage(`Could not disconnect Gmail OAuth: ${e.message}`)
    } finally {
      setIsSavingSettings(false)
    }
  }

  async function handleSyncGoogleOAuth() {
    setSettingsSavedMessage('')
    setIsSyncingEmail(true)
    try {
      const data = await syncGoogleEmailOAuth(token, 15)
      const created = Number(data?.created || 0)
      const processed = Number(data?.processed || 0)
      const failedCount = Array.isArray(data?.failed) ? data.failed.length : 0
      setSettingsSavedMessage(
        `Gmail sync complete: processed ${processed}, created ${created}, failed ${failedCount}.`
      )
      if (data?.settings) {
        setSettingsDraft((current) => ({
          ...current,
          emailCapture: emailCaptureSettingsFromApi(data.settings),
        }))
      }
      setReloadCounter((value) => value + 1)
    } catch (e) {
      setSettingsSavedMessage(`Gmail sync failed: ${e.message}`)
    } finally {
      setIsSyncingEmail(false)
    }
  }

  async function handleSyncImap() {
    setSettingsSavedMessage('')
    setIsSyncingEmail(true)
    try {
      const data = await syncImapEmail(token, 25)
      const created = Number(data?.created || 0)
      const processed = Number(data?.processed || 0)
      const failedCount = Array.isArray(data?.failed) ? data.failed.length : 0
      setSettingsSavedMessage(
        `IMAP sync complete: processed ${processed}, created ${created}, failed ${failedCount}.`
      )
      if (data?.settings) {
        setSettingsDraft((current) => ({
          ...current,
          emailCapture: emailCaptureSettingsFromApi(data.settings),
        }))
      }
      setReloadCounter((value) => value + 1)
    } catch (e) {
      setSettingsSavedMessage(`IMAP sync failed: ${e.message}`)
    } finally {
      setIsSyncingEmail(false)
    }
  }

  async function handlePriorityChange(task, nextLevel) {
    const nextPriority = priorityValueFromLevel(nextLevel)
    if (task.priority === nextPriority) {
      return
    }
    setError('')
    setUpdatingTaskIds((current) => {
      const next = new Set(current)
      next.add(task.id)
      return next
    })
    try {
      await updateTask(token, task.id, { priority: nextPriority })
      setReloadCounter((value) => value + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setUpdatingTaskIds((current) => {
        const next = new Set(current)
        next.delete(task.id)
        return next
      })
    }
  }

  function toggleTaskDetails(task) {
    if (expandedTaskId === task.id) {
      setExpandedTaskId('')
      setDetailsNotes('')
      setDetailsDueDate('')
      setDetailsRecurrence('none')
      setDetailsAttachments([])
      setIsAttachmentDragOver(false)
      setAttachmentPreview(null)
      return
    }
    setExpandedTaskId(task.id)
    setDetailsNotes(task.notes || '')
    setDetailsDueDate(dateInputFromDueAt(task.due_at))
    setDetailsRecurrence(task.recurrence || 'none')
    setDetailsAttachments(normalizeAttachments(task.attachments))
    setIsAttachmentDragOver(false)
    setError('')
  }

  function openAttachmentPreview(attachment) {
    const previewType = attachmentPreviewType(attachment)
    if (!previewType) {
      return
    }

    setAttachmentPreview({
      name: attachment.name,
      url: attachment.url,
      previewType,
    })
  }

  function closeAttachmentPreview() {
    setAttachmentPreview(null)
  }

  function handleAttachmentTitleClick(event, attachment) {
    const previewType = attachmentPreviewType(attachment)
    if (!previewType || isModifiedLinkClick(event)) {
      return
    }
    event.preventDefault()
    openAttachmentPreview(attachment)
  }

  function handleRemoveAttachmentDraft(index) {
    setDetailsAttachments((current) => current.filter((_, currentIndex) => currentIndex !== index))
  }

  async function handleAttachmentFiles(task, files) {
    const selectedFiles = Array.from(files || [])
    if (!selectedFiles.length) {
      return
    }

    setError('')
    setUpdatingTaskIds((current) => {
      const next = new Set(current)
      next.add(task.id)
      return next
    })

    try {
      let latestAttachments = detailsAttachments
      for (const file of selectedFiles) {
        const response = await uploadTaskAttachment(token, task.id, file)
        if (Array.isArray(response?.attachments)) {
          latestAttachments = normalizeAttachments(response.attachments)
        }
      }
      setDetailsAttachments(latestAttachments)
      setTasks((current) =>
        current.map((currentTask) =>
          currentTask.id === task.id
            ? {
                ...currentTask,
                attachments: latestAttachments,
              }
            : currentTask
        )
      )
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setUpdatingTaskIds((current) => {
        const next = new Set(current)
        next.delete(task.id)
        return next
      })
    }
  }

  function handleAttachmentInputChange(task, event) {
    const files = event.target.files
    if (files && files.length) {
      handleAttachmentFiles(task, files)
    }
    event.target.value = ''
  }

  function handleAttachmentDragOver(event) {
    event.preventDefault()
    setIsAttachmentDragOver(true)
  }

  function handleAttachmentDragLeave(event) {
    event.preventDefault()
    if (event.currentTarget.contains(event.relatedTarget)) {
      return
    }
    setIsAttachmentDragOver(false)
  }

  function handleAttachmentDrop(task, event) {
    event.preventDefault()
    setIsAttachmentDragOver(false)
    const files = event.dataTransfer?.files
    if (files && files.length) {
      handleAttachmentFiles(task, files)
    }
  }

  async function handleSaveTaskDetails(task) {
    if (detailsRecurrence !== 'none' && !detailsDueDate) {
      setError('Recurring tasks require a date.')
      return
    }

    setError('')
    setUpdatingTaskIds((current) => {
      const next = new Set(current)
      next.add(task.id)
      return next
    })
    try {
      const payload = {
        notes: detailsNotes,
        attachments: detailsAttachments,
        due_at: detailsDueDate ? dueAtFromDateInput(detailsDueDate) : null,
        recurrence: detailsRecurrence || 'none',
      }
      const updatedTask = await updateTask(token, task.id, payload)
      const normalizedUpdatedAttachments = normalizeAttachments(updatedTask.attachments)
      setDetailsAttachments(normalizedUpdatedAttachments)
      setDetailsDueDate(dateInputFromDueAt(updatedTask.due_at))
      setDetailsRecurrence(updatedTask.recurrence || 'none')
      setTasks((current) =>
        current.map((currentTask) =>
          currentTask.id === task.id
            ? {
                ...currentTask,
                ...updatedTask,
                attachments: normalizedUpdatedAttachments,
              }
            : currentTask
        )
      )
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setUpdatingTaskIds((current) => {
        const next = new Set(current)
        next.delete(task.id)
        return next
      })
    }
  }

  function clearDragState() {
    setDraggedTaskId('')
    setDropTarget(null)
  }

  function taskAreaTextColorStyle(task) {
    if (!areaTextColoringEnabled) {
      return undefined
    }
    if (task.area === 'work') {
      return { color: areaTextColors.work }
    }
    if (task.area === 'personal') {
      return { color: areaTextColors.personal }
    }
    return undefined
  }

  function handleSortColumn(columnKey) {
    setTaskSort((current) => {
      if (current.key !== columnKey) {
        return { key: columnKey, direction: 'asc' }
      }
      if (current.direction === 'asc') {
        return { key: columnKey, direction: 'desc' }
      }
      return { key: '', direction: 'asc' }
    })
  }

  function headerSortAriaValue(columnKey) {
    if (taskSort.key !== columnKey) {
      return 'none'
    }
    return taskSort.direction === 'asc' ? 'ascending' : 'descending'
  }

  function sortIndicator(columnKey) {
    if (taskSort.key !== columnKey) {
      return '↕'
    }
    return taskSort.direction === 'asc' ? '▲' : '▼'
  }

  function handleDragStart(event, taskId) {
    if (!isManualTaskOrder) {
      return
    }
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(taskId))
    setDraggedTaskId(taskId)
  }

  function handleRowDragOver(event, taskId) {
    if (!isManualTaskOrder) {
      return
    }
    if (!draggedTaskId || draggedTaskId === taskId) {
      return
    }
    event.preventDefault()
    const rowRect = event.currentTarget.getBoundingClientRect()
    const position = event.clientY - rowRect.top < rowRect.height / 2 ? 'before' : 'after'
    setDropTarget((current) => {
      if (current?.taskId === taskId && current.position === position) {
        return current
      }
      return { taskId, position }
    })
  }

  async function handleRowDrop(event, taskId) {
    if (!isManualTaskOrder) {
      clearDragState()
      return
    }
    if (!draggedTaskId || draggedTaskId === taskId) {
      clearDragState()
      return
    }
    event.preventDefault()
    const rowRect = event.currentTarget.getBoundingClientRect()
    const placement = event.clientY - rowRect.top < rowRect.height / 2 ? 'before' : 'after'
    try {
      await reorderTask(token, draggedTaskId, taskId, placement)
      setReloadCounter((value) => value + 1)
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      clearDragState()
    }
  }

  function handleBodyDragOver(event) {
    if (!isManualTaskOrder) {
      return
    }
    if (!draggedTaskId) {
      return
    }
    if (event.target.closest('tr[data-task-id]')) {
      return
    }
    event.preventDefault()
    const lastTask = filteredTasks[filteredTasks.length - 1]
    if (lastTask) {
      setDropTarget({ taskId: lastTask.id, position: 'after' })
    }
  }

  async function handleBodyDrop(event) {
    if (!isManualTaskOrder) {
      clearDragState()
      return
    }
    if (!draggedTaskId) {
      return
    }
    if (event.target.closest('tr[data-task-id]')) {
      return
    }
    event.preventDefault()
    const lastTask = filteredTasks[filteredTasks.length - 1]
    if (!lastTask || lastTask.id === draggedTaskId) {
      clearDragState()
      return
    }
    try {
      await reorderTask(token, draggedTaskId, lastTask.id, 'after')
      setReloadCounter((value) => value + 1)
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      clearDragState()
    }
  }

  function renderTaskDetailsPanel(task) {
    return (
      <div className="task-details-panel">
        <div className="task-details-section">
          <label htmlFor={`task-notes-${task.id}`}>Notes</label>
          <textarea
            id={`task-notes-${task.id}`}
            className="task-details-notes"
            value={detailsNotes}
            disabled={updatingTaskIds.has(task.id)}
            onChange={(e) => setDetailsNotes(e.target.value)}
            placeholder="Add notes, email context, or other details."
          />
        </div>
        <div className="task-details-section">
          <label>Schedule</label>
          <div className="task-details-schedule-grid">
            <label className="task-details-field">
              <span>Date</span>
              <input
                type="date"
                value={detailsDueDate}
                disabled={updatingTaskIds.has(task.id)}
                onChange={(e) => setDetailsDueDate(e.target.value)}
              />
            </label>
            <label className="task-details-field">
              <span>Repeat</span>
              <select
                value={detailsRecurrence}
                disabled={updatingTaskIds.has(task.id)}
                onChange={(e) => setDetailsRecurrence(e.target.value)}
              >
                {RECURRENCE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
        <div className="task-details-section">
          <label>Attachments</label>
          <div
            className={
              isAttachmentDragOver
                ? 'task-attachment-dropzone task-attachment-dropzone-active'
                : 'task-attachment-dropzone'
            }
            onDragOver={handleAttachmentDragOver}
            onDragLeave={handleAttachmentDragLeave}
            onDrop={(event) => handleAttachmentDrop(task, event)}
          >
            <p>Drag and drop files here</p>
            <p className="task-attachment-dropzone-sub">or</p>
            <label className="task-attachment-upload-label">
              <input
                type="file"
                multiple
                disabled={updatingTaskIds.has(task.id)}
                onChange={(event) => handleAttachmentInputChange(task, event)}
              />
              Select files
            </label>
          </div>
          {detailsAttachments.length ? (
            <ul className="task-attachment-list">
              {detailsAttachments.map((attachment, index) => {
                const previewType = attachmentPreviewType(attachment)
                return (
                  <li key={`${attachment.url}-${index}`} className="task-attachment-item">
                    <a
                      className="task-attachment-link"
                      href={attachment.url}
                      target={previewType ? undefined : '_blank'}
                      rel={previewType ? undefined : 'noreferrer'}
                      onClick={(event) => handleAttachmentTitleClick(event, attachment)}
                    >
                      {attachment.name}
                    </a>
                    <div className="task-attachment-actions">
                      {previewType ? (
                        <button
                          type="button"
                          className="task-attachment-preview"
                          onClick={() => openAttachmentPreview(attachment)}
                          aria-label={`View ${attachment.name}`}
                          title={`View ${attachment.name}`}
                        >
                          <EyeIcon />
                        </button>
                      ) : null}
                      <a
                        className="task-attachment-download"
                        href={attachment.url}
                        download={attachment.name}
                        aria-label={`Download ${attachment.name}`}
                        title={`Download ${attachment.name}`}
                      >
                        <DownloadIcon />
                      </a>
                      <button
                        type="button"
                        className="task-attachment-remove"
                        disabled={updatingTaskIds.has(task.id)}
                        onClick={() => handleRemoveAttachmentDraft(index)}
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="task-details-empty">No attachments yet.</p>
          )}
        </div>
        <div className="task-details-actions">
          <button
            type="button"
            disabled={updatingTaskIds.has(task.id)}
            onClick={() => handleSaveTaskDetails(task)}
          >
            {updatingTaskIds.has(task.id) ? 'Saving...' : 'Save details'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={isSidebarOpen ? 'layout layout-sidebar-open' : 'layout'}>
      <aside className="sidebar">
        <div className="sidebar-mobile-header">
          <h2>Views</h2>
          <button
            type="button"
            className="sidebar-mobile-close"
            onClick={() => setIsSidebarOpen(false)}
            aria-label="Close views menu"
          >
            Close
          </button>
        </div>
        <ul className="view-list">
          <li>
            <button
              type="button"
              className={activeView.type === 'all' ? 'view-button view-button-active' : 'view-button'}
              onClick={() => openTaskView({ type: 'all' })}
            >
              All Tasks
            </button>
          </li>
          <li>
            <button
              type="button"
              className={
                activeView.type === 'area' && activeView.area === 'work'
                  ? 'view-button view-button-active'
                  : 'view-button'
              }
              onClick={() => openTaskView({ type: 'area', area: 'work' })}
            >
              Work
            </button>
            <ul className="subview-list">
              {workProjects.map((project) => (
                <li key={project.id}>
                  <button
                    type="button"
                    className={
                      activeView.type === 'project' && activeView.projectId === project.id
                        ? 'view-button view-button-sub view-button-active'
                        : 'view-button view-button-sub'
                    }
                    onClick={() => openTaskView({ type: 'project', projectId: project.id })}
                  >
                    {project.name}
                  </button>
                </li>
              ))}
            </ul>
          </li>
          <li>
            <button
              type="button"
              className={
                activeView.type === 'area' && activeView.area === 'personal'
                  ? 'view-button view-button-active'
                  : 'view-button'
              }
              onClick={() => openTaskView({ type: 'area', area: 'personal' })}
            >
              Personal
            </button>
            <ul className="subview-list">
              {personalProjects.map((project) => (
                <li key={project.id}>
                  <button
                    type="button"
                    className={
                      activeView.type === 'project' && activeView.projectId === project.id
                        ? 'view-button view-button-sub view-button-active'
                        : 'view-button view-button-sub'
                    }
                    onClick={() => openTaskView({ type: 'project', projectId: project.id })}
                  >
                    {project.name}
                  </button>
                </li>
              ))}
            </ul>
          </li>
        </ul>
        <div className="sidebar-footer">
          <div className="sidebar-controls">
            <label className="sidebar-toggle">
              <span>By Priority</span>
              <span className="sidebar-switch">
                <input
                  className="sidebar-switch-input"
                  type="checkbox"
                  checked={groupByPriority}
                  onChange={(e) => setGroupByPriority(e.target.checked)}
                />
                <span className="sidebar-switch-slider" aria-hidden="true" />
              </span>
            </label>
            <label className="sidebar-toggle">
              <span>History</span>
              <span className="sidebar-switch">
                <input
                  className="sidebar-switch-input"
                  type="checkbox"
                  checked={includeHistory}
                  onChange={(event) => setIncludeHistory(event.target.checked)}
                />
                <span className="sidebar-switch-slider" aria-hidden="true" />
              </span>
            </label>
          </div>
          <button
            type="button"
            className={
              isSettingsView
                ? 'sidebar-settings-button sidebar-settings-button-active'
                : 'sidebar-settings-button'
            }
            onClick={openSettingsView}
            aria-label="Open settings"
            title="Settings"
          >
            <CogIcon />
            <span>Settings</span>
          </button>
          <button type="button" className="sidebar-logout-button" onClick={onLogout}>
            Log Out
          </button>
        </div>
      </aside>
      {isSidebarOpen ? (
        <button
          type="button"
          className="mobile-sidebar-backdrop"
          onClick={() => setIsSidebarOpen(false)}
          aria-label="Close views menu"
        />
      ) : null}

      <main className="main">
        <header className="topbar">
          <button
            type="button"
            className="mobile-sidebar-open"
            onClick={() => setIsSidebarOpen(true)}
            aria-label="Open views menu"
            title="Views"
          >
            ☰
          </button>
          <div className="topbar-main">
            {isSettingsView ? (
              <div className="settings-topbar-summary">
                <h1>App Settings</h1>
                <p>Manage profile defaults, incoming email capture, privacy, and task list behavior.</p>
              </div>
            ) : (
              <>
                <div className="mobile-list-heading">
                  <h2>{activeViewLabel}</h2>
                  <p>{taskCountLabel}</p>
                </div>
                <div className="search-row">
                  <input placeholder="Search tasks" aria-label="Search tasks" />
                  <div className="search-toggles">
                    <label className="semantic-toggle">
                      <input type="checkbox" /> Semantic
                    </label>
                  </div>
                </div>
                <button
                  type="button"
                  className="desktop-quick-add-trigger"
                  onClick={() => setIsDesktopQuickAddOpen(true)}
                >
                  Add
                </button>
              </>
            )}
          </div>
          {!isSettingsView ? (
            <button
              type="button"
              className="mobile-quick-add-trigger"
              onClick={() => setIsMobileQuickAddOpen(true)}
              aria-label="Add task"
              title="Add task"
            >
              +
            </button>
          ) : null}
        </header>

        {!isSettingsView && isDesktopQuickAddOpen ? (
          <div
            className="desktop-quick-add-popover-backdrop"
            role="presentation"
            onClick={() => setIsDesktopQuickAddOpen(false)}
          >
            <div
              className="desktop-quick-add-popover"
              role="dialog"
              aria-modal="true"
              aria-label="Add task"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="desktop-quick-add-popover-header">
                <h2>Add Task</h2>
                <button type="button" onClick={() => setIsDesktopQuickAddOpen(false)}>
                  Close
                </button>
              </div>
              <QuickAdd
                token={token}
                projects={projects}
                onTaskCreated={handleTaskCreated}
                onProjectCreated={handleProjectCreated}
                className="quick-add-popover-form"
                autoFocusTitle
              />
            </div>
          </div>
        ) : null}

        {!isSettingsView && isMobileQuickAddOpen ? (
          <div
            className="mobile-quick-add-sheet-backdrop"
            role="presentation"
            onClick={() => setIsMobileQuickAddOpen(false)}
          >
            <div
              className="mobile-quick-add-sheet"
              role="dialog"
              aria-modal="true"
              aria-label="Add task"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="mobile-quick-add-sheet-header">
                <h2>Add Task</h2>
                <button type="button" onClick={() => setIsMobileQuickAddOpen(false)}>
                  Close
                </button>
              </div>
              <QuickAdd
                token={token}
                projects={projects}
                onTaskCreated={handleTaskCreated}
                onProjectCreated={handleProjectCreated}
              />
            </div>
          </div>
        ) : null}

        {isSettingsView ? (
          <section className="content">
            <SettingsPage
              token={token}
              settingsDraft={settingsDraft}
              settingsSavedMessage={settingsSavedMessage}
              isSavingSettings={isSavingSettings}
              isSyncingEmail={isSyncingEmail}
              onUpdateSetting={handleUpdateSetting}
              onSaveSettings={handleSaveSettings}
              onResetSettings={handleResetSettings}
              onConnectGoogle={handleConnectGoogleOAuth}
              onDisconnectGoogle={handleDisconnectGoogleOAuth}
              onSyncGoogle={handleSyncGoogleOAuth}
              onSyncImap={handleSyncImap}
              onBackToTasks={() => navigate('/tasks')}
            />
          </section>
        ) : (
          <section className="content">
            <h1 className="tasks-page-title">{activeViewLabel}</h1>
            <p className="tasks-page-count">{taskCountLabel}</p>
            {error ? <p className="error-text">{error}</p> : null}
            <div className="mobile-task-list" role="list">
              {filteredTasks.map((task) => (
                <article
                  key={`mobile-${task.id}`}
                  className={task.status === 'done' ? 'mobile-task-item mobile-task-item-done' : 'mobile-task-item'}
                  role="listitem"
                >
                  <div className="mobile-task-row">
                    <input
                      type="checkbox"
                      className="mobile-task-complete"
                      checked={task.status === 'done'}
                      disabled={updatingTaskIds.has(task.id) || task.status === 'archived'}
                      onChange={(event) => handleToggleComplete(task, event.target.checked)}
                      aria-label={`Mark ${task.title} as complete`}
                    />
                    <div className="mobile-task-copy">
                      <p className="mobile-task-title" style={taskAreaTextColorStyle(task)}>
                        {task.title}
                      </p>
                      <p className="mobile-task-meta">
                        {formatAreaLabel(task.area)}
                        {task.project ? ` • ${projectNameById[task.project] || 'Unknown project'}` : ''}
                      </p>
                      <p className="mobile-task-submeta">
                        {priorityLabelFromValue(task.priority)} • {formatTaskDate(task.due_at)}
                        {task.recurrence && task.recurrence !== 'none'
                          ? ` • ${recurrenceLabel(task.recurrence)}`
                          : ''}
                      </p>
                    </div>
                    <div className="mobile-task-actions">
                      <button
                        type="button"
                        className={
                          expandedTaskId === task.id
                            ? 'mobile-task-action mobile-task-action-active'
                            : 'mobile-task-action'
                        }
                        onClick={() => toggleTaskDetails(task)}
                        aria-label={
                          expandedTaskId === task.id
                            ? `Collapse details for ${task.title}`
                            : `Expand details for ${task.title}`
                        }
                      >
                        i
                      </button>
                      <button
                        type="button"
                        className={
                          openDeleteTaskId === task.id
                            ? 'mobile-task-action mobile-task-action-delete mobile-task-action-active'
                            : 'mobile-task-action mobile-task-action-delete'
                        }
                        onClick={() => toggleDeleteReveal(task.id)}
                        aria-label={openDeleteTaskId === task.id ? 'Hide delete action' : 'Show delete action'}
                      >
                        −
                      </button>
                    </div>
                  </div>
                  {openDeleteTaskId === task.id ? (
                    <div className="mobile-task-delete">
                      <button
                        type="button"
                        className="mobile-task-delete-button"
                        onClick={() => handleDeleteTask(task.id)}
                        disabled={deletingTaskIds.has(task.id)}
                      >
                        {deletingTaskIds.has(task.id) ? 'Deleting...' : 'Delete task'}
                      </button>
                    </div>
                  ) : null}
                  {expandedTaskId === task.id ? (
                    <div className="mobile-task-details">{renderTaskDetailsPanel(task)}</div>
                  ) : null}
                </article>
              ))}
              {!filteredTasks.length ? <p className="mobile-task-empty">No tasks in this view.</p> : null}
            </div>
            <div className="tasks-table-wrap">
              <table className="tasks-table">
                <thead>
                  <tr>
                    <th className="expand-header"></th>
                    <th className="drag-header"></th>
                    <th>Done</th>
                    <th aria-sort={headerSortAriaValue('title')}>
                      <button
                        type="button"
                        className={
                          taskSort.key === 'title'
                            ? 'task-sort-button task-sort-button-active'
                            : 'task-sort-button'
                        }
                        onClick={() => handleSortColumn('title')}
                        aria-label="Sort by title"
                      >
                        <span>Title</span>
                        <span className="task-sort-indicator" aria-hidden="true">
                          {sortIndicator('title')}
                        </span>
                      </button>
                    </th>
                    <th aria-sort={headerSortAriaValue('area')}>
                      <button
                        type="button"
                        className={
                          taskSort.key === 'area'
                            ? 'task-sort-button task-sort-button-active'
                            : 'task-sort-button'
                        }
                        onClick={() => handleSortColumn('area')}
                        aria-label="Sort by area"
                      >
                        <span>Area</span>
                        <span className="task-sort-indicator" aria-hidden="true">
                          {sortIndicator('area')}
                        </span>
                      </button>
                    </th>
                    <th aria-sort={headerSortAriaValue('project')}>
                      <button
                        type="button"
                        className={
                          taskSort.key === 'project'
                            ? 'task-sort-button task-sort-button-active'
                            : 'task-sort-button'
                        }
                        onClick={() => handleSortColumn('project')}
                        aria-label="Sort by project"
                      >
                        <span>Project</span>
                        <span className="task-sort-indicator" aria-hidden="true">
                          {sortIndicator('project')}
                        </span>
                      </button>
                    </th>
                    <th aria-sort={headerSortAriaValue('priority')}>
                      <button
                        type="button"
                        className={
                          taskSort.key === 'priority'
                            ? 'task-sort-button task-sort-button-active'
                            : 'task-sort-button'
                        }
                        onClick={() => handleSortColumn('priority')}
                        aria-label="Sort by priority"
                      >
                        <span>Priority</span>
                        <span className="task-sort-indicator" aria-hidden="true">
                          {sortIndicator('priority')}
                        </span>
                      </button>
                    </th>
                    <th aria-sort={headerSortAriaValue('date')}>
                      <button
                        type="button"
                        className={
                          taskSort.key === 'date'
                            ? 'task-sort-button task-sort-button-active'
                            : 'task-sort-button'
                        }
                        onClick={() => handleSortColumn('date')}
                        aria-label="Sort by date"
                      >
                        <span>Date</span>
                        <span className="task-sort-indicator" aria-hidden="true">
                          {sortIndicator('date')}
                        </span>
                      </button>
                    </th>
                    <th>Repeat</th>
                    <th aria-sort={headerSortAriaValue('created')}>
                      <button
                        type="button"
                        className={
                          taskSort.key === 'created'
                            ? 'task-sort-button task-sort-button-active'
                            : 'task-sort-button'
                        }
                        onClick={() => handleSortColumn('created')}
                        aria-label="Sort by created date"
                      >
                        <span>Created</span>
                        <span className="task-sort-indicator" aria-hidden="true">
                          {sortIndicator('created')}
                        </span>
                      </button>
                    </th>
                    <th className="actions-header"></th>
                  </tr>
                </thead>
                <tbody onDragOver={handleBodyDragOver} onDrop={handleBodyDrop}>
                  {filteredTasks.map((task) => (
                    <Fragment key={task.id}>
                      <tr
                        data-task-id={task.id}
                        className={[
                          task.status === 'done' ? 'task-row-done' : '',
                          openDeleteTaskId === task.id ? 'task-row-actions-open' : '',
                          dropTarget?.taskId === task.id && dropTarget.position === 'before'
                            ? 'task-row-drop-before'
                            : '',
                          dropTarget?.taskId === task.id && dropTarget.position === 'after'
                            ? 'task-row-drop-after'
                            : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        style={taskAreaTextColorStyle(task)}
                        onDragOver={(event) => handleRowDragOver(event, task.id)}
                        onDrop={(event) => handleRowDrop(event, task.id)}
                      >
                        <td className="expand-cell">
                          <div className="task-cell-content">
                            <button
                              type="button"
                              className={
                                expandedTaskId === task.id
                                  ? 'task-expand-toggle task-expand-toggle-open'
                                  : 'task-expand-toggle'
                              }
                              onClick={() => toggleTaskDetails(task)}
                              aria-label={
                                expandedTaskId === task.id
                                  ? `Collapse details for ${task.title}`
                                  : `Expand details for ${task.title}`
                              }
                            >
                              ▶
                            </button>
                          </div>
                        </td>
                        <td className="drag-cell">
                          <button
                            type="button"
                            className={isManualTaskOrder ? 'task-grabber' : 'task-grabber task-grabber-disabled'}
                            draggable={isManualTaskOrder}
                            disabled={!isManualTaskOrder}
                            onDragStart={(event) => handleDragStart(event, task.id)}
                            onDragEnd={clearDragState}
                            aria-label={
                              isManualTaskOrder
                                ? `Reorder ${task.title}`
                                : 'Reordering is available only when no column sort is active'
                            }
                          >
                            ⋮⋮
                          </button>
                        </td>
                        <td className="complete-cell">
                          <div className="task-cell-content">
                            <input
                              type="checkbox"
                              className="task-complete-checkbox"
                              checked={task.status === 'done'}
                              disabled={updatingTaskIds.has(task.id) || task.status === 'archived'}
                              onChange={(e) => handleToggleComplete(task, e.target.checked)}
                              aria-label={`Mark ${task.title} as complete`}
                            />
                          </div>
                        </td>
                        <td>
                          <div className="task-cell-content">
                            {task.title}
                          </div>
                        </td>
                        <td>
                          <div className="task-cell-content">{formatAreaLabel(task.area)}</div>
                        </td>
                        <td>
                          <div className="task-cell-content">
                            {task.project ? projectNameById[task.project] || 'Unknown project' : 'None'}
                          </div>
                        </td>
                        <td>
                          <div className="task-cell-content">
                            <select
                              className={`task-priority-select ${priorityClassFromLevel(
                                priorityLevelFromValue(task.priority)
                              )}`.trim()}
                              value={priorityLevelFromValue(task.priority)}
                              disabled={updatingTaskIds.has(task.id)}
                              onChange={(e) => handlePriorityChange(task, e.target.value)}
                              aria-label={`Set priority for ${task.title}`}
                            >
                              {PRIORITY_OPTIONS.map((option) => (
                                <option key={option.value || 'none'} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </select>
                          </div>
                        </td>
                        <td>
                          <div className="task-cell-content">{formatTaskDate(task.due_at)}</div>
                        </td>
                        <td>
                          <div className="task-cell-content">{recurrenceLabel(task.recurrence)}</div>
                        </td>
                        <td>
                          <div className="task-cell-content">
                            {formatCreatedTimestamp(task.created_at || task.created)}
                          </div>
                        </td>
                        <td className="task-action-cell" data-task-action-id={task.id}>
                          <button
                            type="button"
                            className="task-minus"
                            onClick={() => toggleDeleteReveal(task.id)}
                            aria-label={
                              openDeleteTaskId === task.id ? 'Hide delete action' : 'Show delete action'
                            }
                          >
                            −
                          </button>
                          <button
                            type="button"
                            className="task-delete"
                            onClick={() => handleDeleteTask(task.id)}
                            disabled={deletingTaskIds.has(task.id)}
                          >
                            {deletingTaskIds.has(task.id) ? 'Deleting...' : 'Delete'}
                          </button>
                        </td>
                      </tr>
                      {expandedTaskId === task.id ? (
                        <tr className={task.status === 'done' ? 'task-details-row task-row-done' : 'task-details-row'}>
                          <td colSpan={11} className="task-details-cell">
                            {renderTaskDetailsPanel(task)}
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))}
                  {!filteredTasks.length ? (
                    <tr>
                      <td colSpan={11}>No tasks in this view.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>
      {attachmentPreview ? (
        <div
          className="attachment-preview-backdrop"
          role="presentation"
          onClick={closeAttachmentPreview}
        >
          <div
            className="attachment-preview-modal"
            role="dialog"
            aria-modal="true"
            aria-label={`Preview ${attachmentPreview.name}`}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="attachment-preview-header">
              <p title={attachmentPreview.name}>{attachmentPreview.name}</p>
              <div className="attachment-preview-actions">
                <a href={attachmentPreview.url} download={attachmentPreview.name}>
                  Download
                </a>
                <button type="button" onClick={closeAttachmentPreview}>
                  Close
                </button>
              </div>
            </div>
            <div className="attachment-preview-body">
              {attachmentPreview.previewType === 'image' ? (
                <img src={attachmentPreview.url} alt={attachmentPreview.name} />
              ) : null}
              {attachmentPreview.previewType === 'pdf' ? (
                <PdfCanvasViewer url={attachmentPreview.url} fileName={attachmentPreview.name} />
              ) : null}
              {attachmentPreview.previewType === 'text' ? (
                <TextAttachmentViewer url={attachmentPreview.url} />
              ) : null}
              {attachmentPreview.previewType === 'html' ? (
                <HtmlAttachmentViewer url={attachmentPreview.url} title={attachmentPreview.name} />
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function QuickAddMobile({ token }) {
  const navigate = useNavigate()
  const [projects, setProjects] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    getProjects(token)
      .then((projectData) => {
        if (!active) return
        setProjects(Array.isArray(projectData) ? projectData : [])
        setError('')
      })
      .catch((e) => {
        if (!active) return
        setError(e.message)
      })

    return () => {
      active = false
    }
  }, [token])

  return (
    <div className="mobile-quick-add">
      <header className="mobile-quick-add-header">
        <h1>Quick Add</h1>
        <div className="mobile-quick-add-actions">
          <button type="button" onClick={() => navigate('/tasks')}>
            Tasks
          </button>
          <button type="button" onClick={() => navigate('/settings')}>
            Settings
          </button>
        </div>
      </header>
      {error ? <p className="error-text">{error}</p> : null}
      <QuickAdd
        token={token}
        projects={projects}
        onTaskCreated={() => {}}
        onProjectCreated={(project) =>
          setProjects((current) =>
            current.some((existing) => existing.id === project.id) ? current : [...current, project]
          )
        }
      />
    </div>
  )
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [authReady, setAuthReady] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const token = isAuthenticated ? 'cookie-session' : ''

  const clearSession = useCallback(
    (redirectToLogin = true) => {
      setIsAuthenticated(false)
      setAuthReady(true)
      if (redirectToLogin) {
        navigate('/login', { replace: true })
      }
    },
    [navigate]
  )

  useEffect(() => {
    let active = true
    getAuthSession()
      .then(() => {
        if (!active) return
        setIsAuthenticated(true)
        setAuthReady(true)
      })
      .catch(() => {
        if (!active) return
        setIsAuthenticated(false)
        setAuthReady(true)
      })

    return () => {
      active = false
    }
  }, [])

  useLayoutEffect(() => {
    configureAuthHandlers({
      clearTokens: () => {
        clearSession(true)
      },
    })

    return () => {
      configureAuthHandlers({})
    }
  }, [clearSession])

  async function handleLogout() {
    try {
      await logoutSession()
    } catch {
      // Continue local sign-out even if backend logout/blacklist fails.
    }
    clearSession(true)
  }

  if (!authReady) {
    return null
  }

  if (!isAuthenticated && location.pathname !== '/login') {
    return <Navigate to="/login" replace />
  }

  if (isAuthenticated && location.pathname === '/login') {
    return <Navigate to="/" replace />
  }

  return (
    <Routes>
      <Route path="/login" element={<AuthPage />} />
      <Route path="/" element={<Dashboard token={token} onLogout={handleLogout} />} />
      <Route path="/tasks" element={<Dashboard token={token} onLogout={handleLogout} />} />
      <Route path="/settings" element={<Dashboard token={token} onLogout={handleLogout} />} />
      <Route path="/quick-add" element={<QuickAddMobile token={token} />} />
    </Routes>
  )
}
