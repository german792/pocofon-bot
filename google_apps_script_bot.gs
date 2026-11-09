/**
 * ============================================================================
 * POCO AI — Автономный Telegram-бот для Google Apps Script (24/7 в облаке)
 * ============================================================================
 * Поддерживаемые модели:
 * - Seedance 2.0 Mini / Fast / Pro (39.109.117.93:8092)
 * - Grok Imagine Video / Grok 1.5 (49.233.205.130:8006)
 * - MiniMax H3 Video: Hero / Cinema / Macro со звуком (120.55.55.62)
 * - Qwen Image 3.0 Pro: Коммерческие постеры 1024x1024 (120.55.55.62)
 *
 * ИНСТРУКЦИЯ ПО ЗАПУСКУ В GOOGLE APPS SCRIPT:
 * 1. Откройте https://script.google.com и нажмите «Создать проект» (New project).
 * 2. Удалите весь код в файле Code.gs и вставьте этот код целиком.
 * 3. Нажмите вверху справа «Начать развертывание» (Deploy) -> «Новое развертывание» (New deployment).
 * 4. Выберите тип «Веб-приложение» (Web app):
 *    - Запуск от имени: «Меня» (Me)
 *    - У кого есть доступ: «Все» (Anyone)
 * 5. Нажмите «Развернуть» (Deploy), разрешите доступ и скопируйте полученный URL веб-приложения (заканчивается на /exec).
 * 6. Вставьте скопированный URL ниже в переменную WEB_APP_URL (строка 27).
 * 7. В панели сверху выберите функцию `setWebhook` и нажмите кнопку «Выполнить» (Run).
 * Готово! Бот работает автономно 24/7 на серверах Google!
 */

const BOT_TOKEN = "ВАШ_BOT_TOKEN_ИЗ_BOTFATHER";
const WEB_APP_URL = "ВСТАВЬТЕ_СЮДА_URL_ВАШЕГО_ВЕБ_ПРИЛОЖЕНИЯ_ПОСЛЕ_ДЕПЛОЯ";

const API_V2_BASE_URL = "http://39.109.117.93:8092";
const API_GROK_BASE_URL = "http://49.233.205.130:8006";
const API_MINIMAX_BASE_URL = "http://120.55.55.62/ecommerce-poster-trio";

const MODELS = {
  "s2_mini": { name: "Seedance 2.0 Mini", short: "⚡ 2.0 Mini", backend: "v2", api_id: "doubao-seedance-2-0-mini-260615" },
  "s2_fast": { name: "Seedance 2.0 Fast", short: "🚀 2.0 Fast", backend: "v2", api_id: "doubao-seedance-2-0-fast-260128" },
  "s2_pro": { name: "Seedance 2.0 Pro", short: "🎬 2.0 Pro", backend: "v2", api_id: "doubao-seedance-2-0-260128" },
  "grok": { name: "Grok Imagine Video", short: "🌌 Grok Imagine", backend: "grok", channel: "auto" },
  "grok_15": { name: "Grok Imagine 1.5", short: "🔮 Grok 1.5", backend: "grok", channel: "console" },
  "minimax_hero": { name: "MiniMax H3 (Hero)", short: "🎬 MiniMax Hero", backend: "minimax", style: "minimalist-hero" },
  "minimax_cinema": { name: "MiniMax H3 (Cinema)", short: "🎥 MiniMax Cinema", backend: "minimax", style: "cinematic-lifestyle" },
  "minimax_macro": { name: "MiniMax H3 (Macro)", short: "🔍 MiniMax Macro", backend: "minimax", style: "macro-detail" },
  "qwen_image": { name: "Qwen Image 3.0 Pro", short: "🖼️ Qwen Image", backend: "qwen_image" }
};

// Placeholder 1x1 white PNG in base64 for APIs that require a seed canvas
const WHITE_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==";

/**
 * 1. Функция установки вебхука (запустите её вручную в редакторе после деплоя!)
 */
function setWebhook() {
  if (!WEB_APP_URL || WEB_APP_URL.indexOf("http") !== 0) {
    throw new Error("Сначала вставьте ссылку вашего Web App в переменную WEB_APP_URL на строке 27!");
  }
  const url = "https://api.telegram.org/bot" + BOT_TOKEN + "/setWebhook?url=" + encodeURIComponent(WEB_APP_URL) + "&drop_pending_updates=true";
  const resp = UrlFetchApp.fetch(url);
  Logger.log("Результат привязки вебхука: " + resp.getContentText());
}

/**
 * Функция отключения вебхука (если захотите снова запускать бота с ПК)
 */
function deleteWebhook() {
  const url = "https://api.telegram.org/bot" + BOT_TOKEN + "/deleteWebhook?drop_pending_updates=true";
  const resp = UrlFetchApp.fetch(url);
  Logger.log("Вебхук удален: " + resp.getContentText());
}

/**
 * Обработчик входящих сообщений от Telegram (Webhook)
 */
function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) return ContentService.createTextOutput("OK");
    const update = JSON.parse(e.postData.contents);

    // Защита от повторной отправки одного и того же update_id самим Telegram при долгой генерации
    const cache = CacheService.getScriptCache();
    const updateKey = "upd_" + update.update_id;
    if (cache.get(updateKey)) {
      return ContentService.createTextOutput("OK");
    }
    cache.put(updateKey, "1", 600);

    if (update.message) {
      handleMessage(update.message);
    } else if (update.callback_query) {
      handleCallback(update.callback_query);
    }
  } catch (err) {
    Logger.log("Error in doPost: " + err);
  }
  return ContentService.createTextOutput("OK");
}

function getUserPrefs(userId) {
  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty("prefs_" + userId);
  if (raw) {
    try { return JSON.parse(raw); } catch (e) {}
  }
  return { model_key: "s2_fast", duration: 5, resolution: "720p", ratio: "16:9" };
}

function saveUserPrefs(userId, prefs) {
  PropertiesService.getScriptProperties().setProperty("prefs_" + userId, JSON.stringify(prefs));
}

function saveDraft(userId, draft) {
  PropertiesService.getScriptProperties().setProperty("draft_" + userId, JSON.stringify(draft));
}

function getDraft(userId) {
  const raw = PropertiesService.getScriptProperties().getProperty("draft_" + userId);
  return raw ? JSON.parse(raw) : null;
}

function handleMessage(msg) {
  const chatId = msg.chat.id;
  const userId = msg.from.id;
  const firstName = msg.from.first_name || "друг";
  const text = (msg.text || msg.caption || "").trim();
  const isGroup = msg.chat.type === "group" || msg.chat.type === "supergroup";

  // 1. /start или /help
  if (/^\/(start|help)(@\w+)?$/i.test(text)) {
    const helpText =
      "👋 <b>Привет, " + escapeHtml(firstName) + "!</b>\n\n" +
      "Я автономный облачный бот <b>POCO AI</b> (работаю 24/7 на Google Apps Script)!\n\n" +
      "🤖 <b>Доступные модели:</b>\n" +
      "• <b>🚀 Seedance 2.0 (Mini / Fast / Pro)</b> — генерация видео до 1080p\n" +
      "• <b>🌌 Grok Imagine / 1.5</b> — быстрая генерация видео xAI\n" +
      "• <b>🎬 MiniMax H3 (Hero / Cinema / Macro)</b> — 15-сек видео со звуком\n" +
      "• <b>🖼️ Qwen Image 3.0 Pro</b> — коммерческие постеры и фото 1024x1024\n\n" +
      "✨ <b>Команды:</b>\n" +
      "• <code>/video описание сцены</code> — создать видео\n" +
      "• <code>/image описание постера</code> — создать постер через Qwen Image\n" +
      "• <code>/model</code> — выбрать модель по умолчанию";
    sendTelegram("sendMessage", { chat_id: chatId, text: helpText, parse_mode: "HTML", reply_to_message_id: msg.message_id });
    return;
  }

  // 2. /model
  if (/^\/model(@\w+)?$/i.test(text)) {
    const prefs = getUserPrefs(userId);
    const buttons = [];
    for (var k in MODELS) {
      var m = MODELS[k];
      var lbl = (k === prefs.model_key ? "✅ " : "") + m.name;
      buttons.push([{ text: lbl, callback_data: "pmod:" + k + ":" + userId }]);
    }
    sendTelegram("sendMessage", {
      chat_id: chatId,
      text: "🤖 <b>Выберите модель по умолчанию:</b>\nТекущая: <b>" + MODELS[prefs.model_key].name + "</b>",
      parse_mode: "HTML",
      reply_markup: JSON.stringify({ inline_keyboard: buttons }),
      reply_to_message_id: msg.message_id
    });
    return;
  }

  // 3. /image или /poster
  const imgMatch = text.match(/^\/(image|poster|img|qwen)(?:@\w+)?(?:\s+([\s\S]+))?$/i);
  if (imgMatch) {
    const prompt = (imgMatch[2] || "").trim();
    if (!prompt) {
      sendTelegram("sendMessage", {
        chat_id: chatId,
        text: "🖼️ <b>Укажите описание постера после команды:</b>\n<code>/image футуристичные кроссовки в неоновом свете</code>",
        parse_mode: "HTML",
        reply_to_message_id: msg.message_id
      });
      return;
    }
    runGeneration(chatId, userId, firstName, "qwen_image", prompt, 5, "1024x1024", "1:1", msg.message_id, null);
    return;
  }

  // 4. /video или текст в личке
  let prompt = "";
  const vidMatch = text.match(/^\/(video|gen|v|s2)(?:@\w+)?(?:\s+([\s\S]+))?$/i);
  if (vidMatch) {
    prompt = (vidMatch[2] || "").trim();
    if (!prompt) {
      sendTelegram("sendMessage", {
        chat_id: chatId,
        text: "🎬 <b>Укажите описание видео после команды:</b>\n<code>/video киберпанк спорткар едет по ночному Токио</code>",
        parse_mode: "HTML",
        reply_to_message_id: msg.message_id
      });
      return;
    }
  } else if (!isGroup && !text.startsWith("/")) {
    prompt = text;
  } else {
    return;
  }

  if (!prompt) return;

  const prefs = getUserPrefs(userId);
  const draft = {
    prompt: prompt,
    model_key: prefs.model_key,
    duration: prefs.duration || 5,
    resolution: prefs.resolution || "720p",
    ratio: prefs.ratio || "16:9",
    owner_id: userId,
    user_name: firstName,
    reply_id: msg.message_id
  };
  saveDraft(userId, draft);

  sendTelegram("sendMessage", {
    chat_id: chatId,
    text: formatDraftText(draft),
    parse_mode: "HTML",
    reply_markup: JSON.stringify(buildSettingsKeyboard(draft, userId)),
    reply_to_message_id: msg.message_id
  });
}

function handleCallback(cb) {
  const data = cb.data || "";
  const userId = cb.from.id;
  const chatId = cb.message.chat.id;
  const msgId = cb.message.message_id;
  const parts = data.split(":");
  const action = parts[0];

  if (action === "pmod") {
    const mkey = parts[1];
    const ownerId = parseInt(parts[2], 10);
    if (userId !== ownerId) {
      answerCallback(cb.id, "⚠️ Это меню другого пользователя!", true);
      return;
    }
    const prefs = getUserPrefs(userId);
    prefs.model_key = mkey;
    saveUserPrefs(userId, prefs);

    const buttons = [];
    for (var k in MODELS) {
      var m = MODELS[k];
      var lbl = (k === mkey ? "✅ " : "") + m.name;
      buttons.push([{ text: lbl, callback_data: "pmod:" + k + ":" + userId }]);
    }
    sendTelegram("editMessageText", {
      chat_id: chatId,
      message_id: msgId,
      text: "🤖 <b>Выберите модель по умолчанию:</b>\nТекущая: <b>" + MODELS[mkey].name + "</b>",
      parse_mode: "HTML",
      reply_markup: JSON.stringify({ inline_keyboard: buttons })
    });
    answerCallback(cb.id, "Выбрана " + MODELS[mkey].name, false);
    return;
  }

  const ownerId = parseInt(parts[parts.length - 1], 10);
  if (userId !== ownerId) {
    answerCallback(cb.id, "⚠️ Это меню другого участника!", true);
    return;
  }

  const draft = getDraft(userId);
  if (!draft) {
    answerCallback(cb.id, "Сессия устарела, отправьте /video заново.", true);
    return;
  }

  if (action === "sm") {
    draft.model_key = parts[1];
  } else if (action === "sd") {
    draft.duration = parseInt(parts[1], 10);
  } else if (action === "sr") {
    draft.ratio = parts[1] + ":" + parts[2];
  } else if (action === "can") {
    sendTelegram("editMessageText", {
      chat_id: chatId,
      message_id: msgId,
      text: "❌ <b>Генерация отменена.</b>",
      parse_mode: "HTML"
    });
    answerCallback(cb.id, "Отменено", false);
    return;
  } else if (action === "gen") {
    answerCallback(cb.id, "🚀 Запускаю генерацию...", false);
    runGeneration(chatId, userId, draft.user_name, draft.model_key, draft.prompt, draft.duration, draft.resolution, draft.ratio, draft.reply_id, msgId);
    return;
  }

  saveDraft(userId, draft);
  saveUserPrefs(userId, { model_key: draft.model_key, duration: draft.duration, resolution: draft.resolution, ratio: draft.ratio });

  sendTelegram("editMessageText", {
    chat_id: chatId,
    message_id: msgId,
    text: formatDraftText(draft),
    parse_mode: "HTML",
    reply_markup: JSON.stringify(buildSettingsKeyboard(draft, userId))
  });
  answerCallback(cb.id, "", false);
}

function formatDraftText(draft) {
  const m = MODELS[draft.model_key] || MODELS["s2_fast"];
  return (
    "🎬 <b>Настройки генерации</b>\n\n" +
    "👤 <b>Заказчик:</b> " + escapeHtml(draft.user_name) + "\n" +
    "🤖 <b>Модель:</b> " + m.name + "\n" +
    "📝 <b>Промпт:</b> <i>" + escapeHtml(draft.prompt) + "</i>\n" +
    "⏱ <b>Длительность:</b> " + draft.duration + " сек | 📐 <b>Формат:</b> " + draft.ratio + "\n\n" +
    "👇 <i>Нажмите «Сгенерировать» для запуска:</i>"
  );
}

function buildSettingsKeyboard(draft, ownerId) {
  const rows = [];
  let curRow = [];
  for (var k in MODELS) {
    var m = MODELS[k];
    var lbl = (k === draft.model_key ? "✅ " : "") + m.short;
    curRow.push({ text: lbl, callback_data: "sm:" + k + ":" + ownerId });
    if (curRow.length === 2) {
      rows.push(curRow);
      curRow = [];
    }
  }
  if (curRow.length > 0) rows.push(curRow);

  const durRow = [5, 8, 10, 12].map(function(d) {
    return { text: (d === draft.duration ? "✅ " : "") + d + "с", callback_data: "sd:" + d + ":" + ownerId };
  });
  rows.push(durRow);

  const ratioRow = ["16:9", "9:16", "1:1"].map(function(r) {
    return { text: (r === draft.ratio ? "✅ " : "") + r, callback_data: "sr:" + r + ":" + ownerId };
  });
  rows.push(ratioRow);

  rows.push([
    { text: "🎬 Сгенерировать", callback_data: "gen:" + ownerId },
    { text: "✖️ Отмена", callback_data: "can:" + ownerId }
  ]);
  return { inline_keyboard: rows };
}

/**
 * Основной цикл генерации и поллинга задачи
 */
function runGeneration(chatId, userId, userName, modelKey, prompt, duration, resolution, ratio, replyId, statusMsgId) {
  const m = MODELS[modelKey] || MODELS["s2_fast"];
  const initText =
    "⏳ <b>Генерация запущена (" + m.name + ")...</b>\n\n" +
    "👤 <b>Заказчик:</b> " + escapeHtml(userName) + "\n" +
    "📝 <b>Промпт:</b> <i>" + escapeHtml(prompt) + "</i>\n" +
    "⚙️ <b>Статус:</b> Отправка задачи на GPU-сервер...";

  if (!statusMsgId) {
    const res = sendTelegram("sendMessage", {
      chat_id: chatId,
      text: initText,
      parse_mode: "HTML",
      reply_to_message_id: replyId
    });
    if (res && res.result) statusMsgId = res.result.message_id;
  } else {
    sendTelegram("editMessageText", {
      chat_id: chatId,
      message_id: statusMsgId,
      text: initText,
      parse_mode: "HTML"
    });
  }

  try {
    let mediaUrl = null;
    if (m.backend === "v2") {
      mediaUrl = generateSeedanceV2(m.api_id, prompt, duration, resolution, ratio, chatId, statusMsgId, m.name);
    } else if (m.backend === "grok") {
      mediaUrl = generateGrok(m.channel, prompt, duration, resolution, ratio, chatId, statusMsgId, m.name);
    } else if (m.backend === "minimax") {
      mediaUrl = generateMiniMax(m.style, prompt, chatId, statusMsgId, m.name);
    } else if (m.backend === "qwen_image") {
      mediaUrl = generateQwenImage(prompt, chatId, statusMsgId, m.name);
    }

    if (!mediaUrl) throw new Error("Не удалось получить ссылку на готовый файл.");

    sendTelegram("editMessageText", {
      chat_id: chatId,
      message_id: statusMsgId,
      text: "📤 <b>Готово! Скачиваю и отправляю файл в Telegram...</b>",
      parse_mode: "HTML"
    });

    const fileResp = UrlFetchApp.fetch(mediaUrl, { muteHttpExceptions: true });
    const blob = fileResp.getBlob().setName(m.backend === "qwen_image" ? "poster.png" : "video.mp4");

    const caption =
      "✨ <b>Готово! (" + m.name + ")</b>\n\n" +
      "👤 <b>Заказчик:</b> " + escapeHtml(userName) + "\n" +
      "📝 <b>Промпт:</b> <i>" + escapeHtml(prompt) + "</i>";

    if (m.backend === "qwen_image") {
      sendTelegramMedia("sendPhoto", chatId, "photo", blob, caption, replyId, mediaUrl);
    } else {
      sendTelegramMedia("sendVideo", chatId, "video", blob, caption, replyId, mediaUrl);
    }

    sendTelegram("editMessageText", {
      chat_id: chatId,
      message_id: statusMsgId,
      text: "🎉 <b>Генерация успешно завершена!</b>",
      parse_mode: "HTML"
    });
  } catch (err) {
    sendTelegram("editMessageText", {
      chat_id: chatId,
      message_id: statusMsgId,
      text: "❌ <b>Ошибка генерации (" + m.name + "):</b>\n" + escapeHtml(String(err.message || err)),
      parse_mode: "HTML"
    });
  }
}

/**
 * 1. Генерация через Seedance 2.0 (39.109.117.93:8092)
 */
function generateSeedanceV2(apiId, prompt, duration, resolution, ratio, chatId, statusMsgId, modelName) {
  const payload = {
    model: apiId,
    prompt: prompt + " --rs " + resolution + " --rt " + ratio + " --dur " + duration + " --fps 24 --wm false"
  };
  const resp = UrlFetchApp.fetch(API_V2_BASE_URL + "/api/generate", {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  const data = JSON.parse(resp.getContentText());
  const taskId = data.task_id || data.id;
  if (!taskId) throw new Error(data.error || "Сервер Seedance 2.0 не вернул task_id");

  for (let i = 0; i < 65; i++) {
    Utilities.sleep(4000);
    const stResp = UrlFetchApp.fetch(API_V2_BASE_URL + "/api/task/" + taskId, { muteHttpExceptions: true });
    const stData = JSON.parse(stResp.getContentText());
    const status = (stData.status || "").toLowerCase();

    if (status === "succeeded") {
      return (stData.content && stData.content.video_url) || stData.video_url;
    } else if (status === "failed" || status === "error") {
      throw new Error((stData.error && stData.error.message) || "Ошибка рендеринга Seedance");
    }
  }
  throw new Error("Превышено время ожидания ответа от Seedance 2.0");
}

/**
 * 2. Генерация через Grok Imagine Video (49.233.205.130:8006)
 */
function generateGrok(channel, prompt, duration, resolution, ratio, chatId, statusMsgId, modelName) {
  const payload = {
    prompt: prompt,
    duration: duration === 5 ? 6 : duration,
    aspect_ratio: ratio,
    resolution: resolution,
    channel: channel || "auto",
    image_file: "",
    image_url: ""
  };
  const resp = UrlFetchApp.fetch(API_GROK_BASE_URL + "/api/video/generate", {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  const data = JSON.parse(resp.getContentText());
  const reqId = data.request_id;
  if (!reqId) throw new Error(data.detail || "Сервер Grok не вернул ID задачи");

  for (let i = 0; i < 60; i++) {
    Utilities.sleep(3500);
    const stResp = UrlFetchApp.fetch(API_GROK_BASE_URL + "/api/video/" + reqId, { muteHttpExceptions: true });
    const stData = JSON.parse(stResp.getContentText());
    if (stData.status === "done") {
      return API_GROK_BASE_URL + "/api/video/" + reqId + "/content";
    } else if (stData.status === "failed" || stData.status === "error") {
      throw new Error(stData.detail || "Ошибка генерации Grok");
    }
  }
  throw new Error("Превышено время ожидания Grok Imagine");
}

/**
 * 3. Генерация через MiniMax H3 Video (120.55.55.62)
 */
function generateMiniMax(style, prompt, chatId, statusMsgId, modelName) {
  const payload = {
    productImage: { name: "input.png", dataUrl: "data:image/png;base64," + WHITE_PNG_B64 },
    productName: prompt.substring(0, 60),
    sellingPoints: prompt,
    videoStyle: style || "minimalist-hero"
  };
  const resp = UrlFetchApp.fetch(API_MINIMAX_BASE_URL + "/api/video/generate", {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  const data = JSON.parse(resp.getContentText());
  const runId = data.runId;
  if (!runId) throw new Error(data.error || "Сервер MiniMax не вернул runId");

  for (let i = 0; i < 70; i++) {
    Utilities.sleep(4000);
    const stResp = UrlFetchApp.fetch(API_MINIMAX_BASE_URL + "/api/video-status?runId=" + encodeURIComponent(runId), { muteHttpExceptions: true });
    const stData = JSON.parse(stResp.getContentText());
    if (stData.status === "completed" || stData.status === "done") {
      const vUrl = stData.videoUrl || stData.remoteVideoUrl;
      return vUrl.indexOf("http") === 0 ? vUrl : API_MINIMAX_BASE_URL + "/" + vUrl.replace(/^\//, "");
    } else if (stData.status === "failed" || stData.status === "error") {
      throw new Error(stData.error || "Ошибка генерации MiniMax H3");
    }
  }
  throw new Error("Превышено время ожидания MiniMax H3");
}

/**
 * 4. Генерация через Qwen Image 3.0 Pro (120.55.55.62)
 */
function generateQwenImage(prompt, chatId, statusMsgId, modelName) {
  const payload = {
    productImage: { name: "product.png", dataUrl: "data:image/png;base64," + WHITE_PNG_B64 },
    productName: prompt.substring(0, 60),
    category: "General",
    sellingPoints: prompt,
    targetAudience: "General audience",
    imageModel: "qwen-image-3.0-pro",
    textModel: "qwen-max"
  };
  const resp = UrlFetchApp.fetch(API_MINIMAX_BASE_URL + "/api/generate", {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  const data = JSON.parse(resp.getContentText());
  const runId = data.runId;
  if (!runId) throw new Error(data.error || "Сервер Qwen Image не вернул runId");

  for (let i = 0; i < 65; i++) {
    Utilities.sleep(3500);
    const stResp = UrlFetchApp.fetch(API_MINIMAX_BASE_URL + "/api/run-status?runId=" + encodeURIComponent(runId), { muteHttpExceptions: true });
    const stData = JSON.parse(stResp.getContentText());
    const posters = stData.posters || [];
    for (let j = 0; j < posters.length; j++) {
      if (posters[j].imageUrl) {
        const iUrl = posters[j].imageUrl;
        return iUrl.indexOf("http") === 0 ? iUrl : API_MINIMAX_BASE_URL + "/" + iUrl.replace(/^\//, "");
      }
    }
    if (stData.status === "failed" || stData.status === "error") {
      throw new Error(stData.error || "Ошибка генерации Qwen Image");
    }
  }
  throw new Error("Превышено время ожидания Qwen Image");
}

/**
 * Вспомогательные функции Telegram API
 */
function sendTelegram(method, payload) {
  const url = "https://api.telegram.org/bot" + BOT_TOKEN + "/" + method;
  const resp = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  try { return JSON.parse(resp.getContentText()); } catch (e) { return null; }
}

function sendTelegramMedia(method, chatId, fieldName, blob, caption, replyId, directUrl) {
  const url = "https://api.telegram.org/bot" + BOT_TOKEN + "/" + method;
  const form = {
    chat_id: String(chatId),
    caption: caption,
    parse_mode: "HTML",
    reply_markup: JSON.stringify({
      inline_keyboard: [[{ text: "🌐 Открыть оригинал", url: directUrl }]]
    })
  };
  if (replyId) form.reply_to_message_id = String(replyId);
  form[fieldName] = blob;

  UrlFetchApp.fetch(url, {
    method: "post",
    payload: form,
    muteHttpExceptions: true
  });
}

function answerCallback(callbackId, text, showAlert) {
  sendTelegram("answerCallbackQuery", {
    callback_query_id: callbackId,
    text: text,
    show_alert: Boolean(showAlert)
  });
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
