(function () {
  const SETTINGS_STORAGE_KEY = "taskhub.outlook.addin.settings";
  const ROAMING_KEY_URL = "taskhubUrl";
  const ROAMING_KEY_TOKEN = "taskhubIngestToken";
  const ROAMING_KEY_RECIPIENT = "taskhubRecipientEmail";
  const INGEST_PATH = "/capture/email/inbound";

  const elements = {};

  Office.onReady((info) => {
    if (info.host !== Office.HostType.Outlook) {
      return;
    }

    cacheElements();
    bindHandlers();
    loadSettings();
    renderCurrentMessage();
    setStatus("Ready.", "info");
  });

  function cacheElements() {
    elements.taskHubUrl = document.getElementById("taskhub-url");
    elements.recipientEmail = document.getElementById("recipient-email");
    elements.ingestToken = document.getElementById("ingest-token");
    elements.saveButton = document.getElementById("save-settings");
    elements.captureButton = document.getElementById("capture-email");
    elements.currentItem = document.getElementById("current-item");
    elements.status = document.getElementById("status");
  }

  function bindHandlers() {
    elements.saveButton.addEventListener("click", async () => {
      try {
        const settings = readSettingsFromForm();
        validateSettings(settings);
        await saveSettings(settings);
        setStatus("Settings saved.", "success");
      } catch (error) {
        setStatus(error.message || "Failed to save settings.", "error");
      }
    });

    elements.captureButton.addEventListener("click", async () => {
      const previousText = elements.captureButton.textContent;
      elements.captureButton.disabled = true;
      elements.captureButton.textContent = "Adding...";
      setStatus("Capturing current email...", "info");

      try {
        const settings = readSettingsFromForm();
        validateSettings(settings);
        await saveSettings(settings);

        const emlBase64 = await getCurrentMessageAsEmlBase64();
        const emlBlob = base64ToBlob(emlBase64, "message/rfc822");
        const filename = `${sanitizeFilename(getCurrentMessageSubject() || "outlook-message")}.eml`;
        const responseData = await postToTaskHub(settings, emlBlob, filename);

        const createdTitle = typeof responseData?.title === "string" ? responseData.title : "";
        if (createdTitle) {
          setStatus(`Task created: ${createdTitle}`, "success");
        } else {
          setStatus("Task created successfully.", "success");
        }
      } catch (error) {
        setStatus(error.message || "Failed to create task.", "error");
      } finally {
        elements.captureButton.disabled = false;
        elements.captureButton.textContent = previousText;
      }
    });
  }

  function loadSettings() {
    const fallback = getFallbackSettings();
    const roamingSettings = Office.context?.roamingSettings;
    const fromRoaming = {
      taskHubUrl: readRoamingValue(roamingSettings, ROAMING_KEY_URL),
      ingestToken: readRoamingValue(roamingSettings, ROAMING_KEY_TOKEN),
      recipientEmail: readRoamingValue(roamingSettings, ROAMING_KEY_RECIPIENT),
    };

    const merged = {
      taskHubUrl:
        fromRoaming.taskHubUrl || fallback.taskHubUrl || safeCurrentOrigin() || "https://taskhub.example.com",
      ingestToken: fromRoaming.ingestToken || fallback.ingestToken || "",
      recipientEmail: fromRoaming.recipientEmail || fallback.recipientEmail || "",
    };

    elements.taskHubUrl.value = merged.taskHubUrl;
    elements.ingestToken.value = merged.ingestToken;
    elements.recipientEmail.value = merged.recipientEmail;
  }

  function readRoamingValue(roamingSettings, key) {
    if (!roamingSettings || typeof roamingSettings.get !== "function") {
      return "";
    }
    const value = roamingSettings.get(key);
    return typeof value === "string" ? value : "";
  }

  function readSettingsFromForm() {
    return {
      taskHubUrl: normalizeBaseUrl(elements.taskHubUrl.value),
      ingestToken: String(elements.ingestToken.value || "").trim(),
      recipientEmail: String(elements.recipientEmail.value || "").trim().toLowerCase(),
    };
  }

  function validateSettings(settings) {
    if (!settings.taskHubUrl) {
      throw new Error("Task Hub URL is required.");
    }
    if (!settings.ingestToken) {
      throw new Error("Ingest token is required.");
    }
    if (!settings.recipientEmail || !settings.recipientEmail.includes("@")) {
      throw new Error("Inbound recipient email is required.");
    }
  }

  async function saveSettings(settings) {
    setFallbackSettings(settings);

    const roamingSettings = Office.context?.roamingSettings;
    if (!roamingSettings || typeof roamingSettings.set !== "function") {
      return;
    }

    roamingSettings.set(ROAMING_KEY_URL, settings.taskHubUrl);
    roamingSettings.set(ROAMING_KEY_TOKEN, settings.ingestToken);
    roamingSettings.set(ROAMING_KEY_RECIPIENT, settings.recipientEmail);

    await new Promise((resolve, reject) => {
      roamingSettings.saveAsync((result) => {
        if (result.status === Office.AsyncResultStatus.Succeeded) {
          resolve();
          return;
        }
        const message = result.error?.message || "Unable to save roaming settings.";
        reject(new Error(message));
      });
    });
  }

  async function postToTaskHub(settings, emlBlob, filename) {
    const endpoint = `${settings.taskHubUrl}${INGEST_PATH}`;
    const formData = new FormData();
    formData.append("email", emlBlob, filename);
    formData.append("recipient", settings.recipientEmail);

    const sender = getSenderEmailAddress();
    if (sender) {
      formData.append("sender", sender);
    }

    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "X-TaskHub-Ingest-Token": settings.ingestToken,
      },
      body: formData,
    });

    const responseBody = await parseResponseBody(response);
    if (!response.ok) {
      const responseMessage = responseBody?.message || response.statusText || "Task Hub rejected the request.";
      throw new Error(`Task Hub error (${response.status}): ${responseMessage}`);
    }
    return responseBody;
  }

  async function parseResponseBody(response) {
    const contentType = String(response.headers.get("content-type") || "").toLowerCase();
    if (contentType.includes("application/json")) {
      return response.json();
    }

    const text = await response.text();
    return text ? { message: text } : {};
  }

  async function getCurrentMessageAsEmlBase64() {
    const item = Office.context?.mailbox?.item;
    const messageType = Office.MailboxEnums?.ItemType?.Message || "message";
    const itemType = String(item?.itemType || "").toLowerCase();
    if (!item || itemType !== String(messageType).toLowerCase()) {
      throw new Error("Open an email in read mode, then run Add Current Email.");
    }
    if (typeof item.getAsFileAsync !== "function") {
      throw new Error("This Outlook client does not support email export for add-ins.");
    }

    return new Promise((resolve, reject) => {
      item.getAsFileAsync((result) => {
        if (result.status !== Office.AsyncResultStatus.Succeeded) {
          const message = result.error?.message || "Outlook could not export this email.";
          reject(new Error(message));
          return;
        }

        const base64 = String(result.value || "").trim();
        if (!base64) {
          reject(new Error("Outlook returned an empty email payload."));
          return;
        }
        resolve(base64);
      });
    });
  }

  function base64ToBlob(base64, contentType) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Blob([bytes], { type: contentType });
  }

  function renderCurrentMessage() {
    const subject = getCurrentMessageSubject();
    if (!subject) {
      elements.currentItem.textContent = "No email selected.";
      return;
    }
    elements.currentItem.textContent = `Current email: ${subject}`;
  }

  function getCurrentMessageSubject() {
    const subject = Office.context?.mailbox?.item?.subject;
    return typeof subject === "string" ? subject.trim() : "";
  }

  function getSenderEmailAddress() {
    const from = Office.context?.mailbox?.item?.from;
    const candidate = from?.emailAddress || from?.smtpAddress || "";
    return String(candidate || "").trim().toLowerCase();
  }

  function normalizeBaseUrl(rawValue) {
    let value = String(rawValue || "").trim();
    if (!value) {
      return "";
    }
    if (!/^https?:\/\//i.test(value)) {
      value = `https://${value}`;
    }
    return value.replace(/\/+$/, "");
  }

  function sanitizeFilename(value) {
    const clean = String(value || "")
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
      .replace(/\s+/g, " ")
      .trim();
    return clean || "outlook-message";
  }

  function safeCurrentOrigin() {
    try {
      return normalizeBaseUrl(window.location.origin || "");
    } catch (_error) {
      return "";
    }
  }

  function getFallbackSettings() {
    try {
      const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
      if (!raw) {
        return {};
      }
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") {
        return {};
      }
      return {
        taskHubUrl: typeof parsed.taskHubUrl === "string" ? parsed.taskHubUrl : "",
        ingestToken: typeof parsed.ingestToken === "string" ? parsed.ingestToken : "",
        recipientEmail: typeof parsed.recipientEmail === "string" ? parsed.recipientEmail : "",
      };
    } catch (_error) {
      return {};
    }
  }

  function setFallbackSettings(settings) {
    try {
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    } catch (_error) {
      // Ignore local fallback write errors.
    }
  }

  function setStatus(message, level) {
    elements.status.textContent = message;
    elements.status.dataset.level = level || "info";
  }
})();
