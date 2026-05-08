// ======================== 加载配置 ========================
const fs = require("fs");
const path = require("path");
const https = require("https");
const http = require("http");
const { ipcRenderer } = require("electron");

let DEEPSEEK_API_KEY = "";
let API_URL = "https://api.deepseek.com/chat/completions";
let MODEL_NAME = "deepseek-chat";

function loadConfig() {
  const jsonPath = path.join(__dirname, "config.json");
  const yamlPath = path.join(__dirname, "config.yaml");

  try {
    if (fs.existsSync(jsonPath)) {
      const cfg = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));
      DEEPSEEK_API_KEY = cfg.apiKey || "";
      API_URL = cfg.apiUrl || API_URL;
      MODEL_NAME = cfg.model || MODEL_NAME;
    } else if (fs.existsSync(yamlPath)) {
      const raw = fs.readFileSync(yamlPath, "utf-8");
      for (const line of raw.split("\n")) {
        const m = line.match(/^\s*(\w+)\s*:\s*["']?(.+?)["']?\s*$/);
        if (m) {
          if (m[1] === "api_key") DEEPSEEK_API_KEY = m[2].replace(/["']/g, "");
          if (m[1] === "api_url") API_URL = m[2].replace(/["']/g, "");
          if (m[1] === "model") MODEL_NAME = m[2].replace(/["']/g, "");
        }
      }
    }
  } catch (e) {
    console.error("配置加载失败:", e.message);
  }
}
loadConfig();

// ======================== 全局 ========================
const quill = new Quill("#editor", {
  theme: "snow",
  modules: { toolbar: "#toolbar" }
});

let currentDocId = null;
let isAILoading = false;
let isChatLoading = false;
let saveTimer = null;
let isPreviewMode = false;
let lastSelection = null;  // 缓存选区，防止点击按钮时编辑器失焦导致选区丢失

// ======================== 辅助函数 ========================
function showToast(msg, isError = false) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = msg;
  toast.style.backgroundColor = isError ? "#dc2626" : "#0f172a";
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2200);
}

// 简单语言检测：统计CJK字符占比，>30%判为中文
function detectLanguage(text) {
  let cjk = 0, latin = 0;
  for (const ch of text) {
    if (/[一-鿿㐀-䶿]/.test(ch)) cjk++;
    else if (/[a-zA-Z]/.test(ch)) latin++;
  }
  const total = cjk + latin;
  if (total === 0) return "zh";
  return cjk / total > 0.3 ? "zh" : "en";
}

// ======================== 文件操作 ========================

// 获取当前文档关联的文件路径
function getCurrentFilePath() {
  if (!currentDocId) return null;
  const raw = localStorage.getItem(currentDocId);
  if (!raw) return null;
  try {
    const doc = JSON.parse(raw);
    return doc.filePath || null;
  } catch (e) {
    return null;
  }
}

// 更新文档的文件路径
function setCurrentFilePath(filePath) {
  if (!currentDocId) return;
  const raw = localStorage.getItem(currentDocId);
  if (!raw) return;
  const doc = JSON.parse(raw);
  doc.filePath = filePath;
  doc.title = path.basename(filePath, path.extname(filePath));
  localStorage.setItem(currentDocId, JSON.stringify(doc));
  refreshFileList();
}

// 写文件到磁盘
function writeFile(filePath, content) {
  try {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(filePath, content, "utf-8");
    return true;
  } catch (err) {
    showToast("写入失败: " + err.message, true);
    return false;
  }
}

// ====== 保存（Ctrl+S）======
async function saveDocument() {
  if (!currentDocId) return showToast("请先创建文档", true);
  let filePath = getCurrentFilePath();

  if (!filePath) {
    // 未关联文件 → 弹出另存为
    return saveDocumentAs();
  }

  // 已有路径 → 直接覆盖保存
  const data = buildSaveData();
  const ext = path.extname(filePath).toLowerCase();
  let content;

  if (ext === ".md") content = data.contentMd;
  else if (ext === ".html") content = wrapHtml(data.title, data.contentHtml);
  else content = JSON.stringify(data, null, 2);

  if (writeFile(filePath, content)) {
    updateDocTimestamp();
    showToast("已保存: " + path.basename(filePath));
  }
}

// ====== 另存为（Ctrl+Shift+S）======
async function saveDocumentAs() {
  if (!currentDocId) return showToast("请先创建文档", true);
  const doc = JSON.parse(localStorage.getItem(currentDocId));

  const result = await ipcRenderer.invoke("show-save-dialog",
    (doc.title || "untitled") + ".json",
    [
      { name: "JSON 文档 (保留格式)", extensions: ["json"] },
      { name: "所有文件", extensions: ["*"] }
    ]
  );
  if (result.canceled || !result.filePath) return;

  const data = buildSaveData();
  if (writeFile(result.filePath, JSON.stringify(data, null, 2))) {
    setCurrentFilePath(result.filePath);
    updateDocTimestamp();
    showToast("已保存: " + path.basename(result.filePath));
  }
}

// ====== 导出 Markdown ======
async function exportMarkdown() {
  if (!currentDocId) return showToast("请先创建文档", true);
  const doc = JSON.parse(localStorage.getItem(currentDocId));
  const result = await ipcRenderer.invoke("show-save-dialog",
    (doc.title || "untitled") + ".md",
    [{ name: "Markdown 文件", extensions: ["md"] }]
  );
  if (result.canceled || !result.filePath) return;

  const html = quill.root.innerHTML;
  const md = turndownService.turndown(html);
  if (writeFile(result.filePath, md)) {
    showToast("已导出 Markdown: " + path.basename(result.filePath));
  }
}

// ====== 导出 TXT ======
async function exportTxt() {
  if (!currentDocId) return showToast("请先创建文档", true);
  const doc = JSON.parse(localStorage.getItem(currentDocId));
  const result = await ipcRenderer.invoke("show-save-dialog",
    (doc.title || "untitled") + ".txt",
    [{ name: "纯文本文件", extensions: ["txt"] }]
  );
  if (result.canceled || !result.filePath) return;

  const text = quill.getText();
  if (writeFile(result.filePath, text)) {
    showToast("已导出 TXT: " + path.basename(result.filePath));
  }
}

// ====== 导出 HTML ======
async function exportHtml() {
  if (!currentDocId) return showToast("请先创建文档", true);
  const doc = JSON.parse(localStorage.getItem(currentDocId));
  const result = await ipcRenderer.invoke("show-save-dialog",
    (doc.title || "untitled") + ".html",
    [{ name: "HTML 网页", extensions: ["html", "htm"] }]
  );
  if (result.canceled || !result.filePath) return;

  const html = wrapHtml(doc.title, quill.root.innerHTML);
  if (writeFile(result.filePath, html)) {
    showToast("已导出 HTML: " + path.basename(result.filePath));
  }
}

// ====== 导出 PDF（独立隐藏窗口渲染，仅文档内容）======
async function exportPdf() {
  if (!currentDocId) return showToast("请先创建文档", true);
  const doc = JSON.parse(localStorage.getItem(currentDocId));
  const result = await ipcRenderer.invoke("show-save-dialog",
    (doc.title || "untitled") + ".pdf",
    [{ name: "PDF 文件", extensions: ["pdf"] }]
  );
  if (result.canceled || !result.filePath) return;

  const pdfHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>${escapeHtml(doc.title)}</title>
<style>
  @page { size: A4; margin: 20mm; }
  body {
    font-family: 'Microsoft YaHei', 'SimSun', 'Segoe UI', sans-serif;
    font-size: 14pt;
    line-height: 1.8;
    color: #1e293b;
    max-width: 100%;
  }
  h1, h2, h3 { color: #1e3a8a; }
  img { max-width: 100%; height: auto; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; }
  td, th { border: 1px solid #cbd5e1; padding: 8px 12px; }
  blockquote {
    border-left: 4px solid #3b82f6;
    margin: 12px 0;
    padding: 8px 16px;
    background: #f8fafc;
    color: #475569;
  }
  pre {
    background: #f1f5f9;
    padding: 12px 16px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 12pt;
  }
  code { font-family: 'Fira Code', 'Consolas', monospace; }
</style>
</head>
<body>${quill.root.innerHTML}</body>
</html>`;

  const res = await ipcRenderer.invoke("export-pdf", pdfHtml, result.filePath);
  if (res.success) {
    showToast("已导出 PDF: " + path.basename(result.filePath));
  } else {
    showToast("PDF 导出失败: " + (res.error || "未知错误"), true);
  }
}

// ====== 导出 DOC (Word 兼容 HTML) ======
async function exportDoc() {
  if (!currentDocId) return showToast("请先创建文档", true);
  const doc = JSON.parse(localStorage.getItem(currentDocId));
  const result = await ipcRenderer.invoke("show-save-dialog",
    (doc.title || "untitled") + ".doc",
    [{ name: "Word 文档", extensions: ["doc"] }]
  );
  if (result.canceled || !result.filePath) return;

  const html = docToWordHtml(doc.title, quill.root.innerHTML);
  // .doc 实际用 HTML 格式，Word 能直接打开
  const buf = Buffer.from(html, "utf-8");
  try {
    fs.writeFileSync(result.filePath, buf);
    showToast("已导出 DOC: " + path.basename(result.filePath));
  } catch (err) {
    showToast("导出失败: " + err.message, true);
  }
}

// ====== 打开文档（Ctrl+O）======
async function openDocument() {
  const result = await ipcRenderer.invoke("show-open-dialog");
  if (result.canceled || result.filePaths.length === 0) return;

  const filePath = result.filePaths[0];
  try {
    const ext = path.extname(filePath).toLowerCase();
    const raw = fs.readFileSync(filePath, "utf-8");

    let doc;
    if (ext === ".json") {
      const parsed = JSON.parse(raw);
      doc = {
        title: parsed.title || path.basename(filePath, ext),
        contentDelta: parsed.contentDelta || { ops: [{ insert: raw }] },
        content: parsed.contentHtml || raw,
        updatedAt: Date.now(),
        filePath: filePath
      };
      if (parsed.contentDelta && parsed.contentDelta.ops) {
        // 纯 JSON 格式文档
      } else if (parsed.contentHtml) {
        doc.contentDelta = null;
        doc.content = parsed.contentHtml;
      }
    } else if (ext === ".md" || ext === ".txt") {
      doc = {
        title: path.basename(filePath, ext),
        contentDelta: null,
        content: null,
        updatedAt: Date.now(),
        filePath: filePath
      };
      // Markdown/纯文本 → 直接显示文字
      doc._plainText = raw;
    } else {
      // HTML 等
      doc = {
        title: path.basename(filePath, ext),
        contentDelta: null,
        content: raw,
        updatedAt: Date.now(),
        filePath: filePath
      };
    }

    // 存到 localStorage
    const id = "doc_" + Date.now();
    localStorage.setItem(id, JSON.stringify(doc));
    currentDocId = id;

    // 加载到编辑器
    if (doc.contentDelta && doc.contentDelta.ops) {
      quill.setContents(doc.contentDelta);
    } else if (doc.content) {
      quill.clipboard.dangerouslyPasteHTML(doc.content);
    } else if (doc._plainText) {
      quill.setText(doc._plainText);
    } else {
      quill.setText("");
    }

    refreshFileList();
    showToast("已打开: " + path.basename(filePath));
  } catch (err) {
    showToast("打开失败: " + err.message, true);
  }
}

// —— 保存辅助函数 ——
function buildSaveData() {
  const html = quill.root.innerHTML;
  const md = turndownService.turndown(html);
  return {
    title: "",
    contentDelta: quill.getContents(),
    contentHtml: html,
    contentMd: md,
    updatedAt: Date.now()
  };
}

function updateDocTimestamp() {
  if (!currentDocId) return;
  const raw = localStorage.getItem(currentDocId);
  if (!raw) return;
  const doc = JSON.parse(raw);
  doc.contentDelta = quill.getContents();
  doc.updatedAt = Date.now();
  localStorage.setItem(currentDocId, JSON.stringify(doc));
}

// 完整 HTML 包装器
function wrapHtml(title, bodyHtml) {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>${escapeHtml(title)}</title>
<style>
body{max-width:900px;margin:40px auto;padding:20px;font-family:'Microsoft YaHei',sans-serif;font-size:16px;line-height:1.8;color:#1e293b}
h1,h2,h3{color:#1e3a8a}
img{max-width:100%}
</style>
</head>
<body>${bodyHtml}</body>
</html>`;
}

function escapeHtml(str) {
  return str.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]));
}

// Word 兼容 HTML（mso 命名空间让 Word 识别为原生文档）
function docToWordHtml(title, bodyHtml) {
  return `<html xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:w="urn:schemas-microsoft-com:office:word"
 xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="UTF-8">
<title>${escapeHtml(title)}</title>
<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View></w:WordDocument></xml><![endif]-->
<style>
@page { size: A4; margin: 2cm; }
body { font-family: 'Microsoft YaHei', sans-serif; font-size: 14pt; line-height: 1.6; }
</style>
</head><body>${bodyHtml}</body></html>`;
}

// ======================== AI 调用 ========================
const MODEL_FALLBACK = ["deepseek-chat", "deepseek-v4-flash", "deepseek-reasoner"];

function callAI(prompt, systemMsg = "You are a helpful assistant.", retryIdx = 0) {
  return new Promise((resolve, reject) => {
    if (!DEEPSEEK_API_KEY) {
      showToast("请先在 config.json 中配置 API Key", true);
      return reject(new Error("未配置 API Key"));
    }
    if (isAILoading) return reject(new Error("AI 正忙，请稍后"));
    isAILoading = true;

    const model = MODEL_FALLBACK[Math.min(retryIdx, MODEL_FALLBACK.length - 1)];
    const url = new URL(API_URL);
    const postData = JSON.stringify({
      model: model,
      messages: [
        { role: "system", content: systemMsg },
        { role: "user", content: prompt }
      ],
      temperature: 0.7
    });

    const options = {
      hostname: url.hostname,
      port: url.port || 443,
      path: url.pathname,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${DEEPSEEK_API_KEY}`,
        "Content-Length": Buffer.byteLength(postData)
      }
    };

    const transport = url.protocol === "https:" ? https : http;
    const req = transport.request(options, (res) => {
      let body = "";
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        isAILoading = false;
        try {
          if (res.statusCode < 200 || res.statusCode >= 300) {
            if ((res.statusCode === 503 || res.statusCode === 429) && retryIdx < MODEL_FALLBACK.length - 1) {
              showToast(`模型 ${model} 繁忙，自动切换...`);
              setTimeout(() => {
                callAI(prompt, systemMsg, retryIdx + 1).then(resolve).catch(reject);
              }, 1000);
              return;
            }
            showToast(`API错误 ${res.statusCode}: ${body}`, true);
            return reject(new Error(`API错误 ${res.statusCode}`));
          }
          const data = JSON.parse(body);
          resolve(data.choices[0].message.content);
        } catch (err) {
          showToast("API 响应解析失败", true);
          reject(err);
        }
      });
    });

    req.on("error", (err) => {
      isAILoading = false;
      showToast(`网络请求失败: ${err.message}`, true);
      reject(err);
    });

    req.setTimeout(60000, () => {
      isAILoading = false;
      req.destroy();
      showToast("请求超时，请检查网络", true);
      reject(new Error("请求超时"));
    });

    req.write(postData);
    req.end();
  });
}

// ======================== 文档管理 ========================
function saveCurrentDoc() {
  if (!currentDocId) return;
  const raw = localStorage.getItem(currentDocId);
  if (!raw) return;
  const doc = JSON.parse(raw);
  doc.contentDelta = quill.getContents();
  doc.updatedAt = Date.now();
  localStorage.setItem(currentDocId, JSON.stringify(doc));
}

function debounceSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveCurrentDoc();
    // 如果有关联文件路径，同时保存到磁盘
    const fp = getCurrentFilePath();
    if (fp) {
      const data = buildSaveData();
      const ext = path.extname(fp).toLowerCase();
      let content;
      if (ext === ".md") content = data.contentMd;
      else if (ext === ".html") content = wrapHtml("Document", data.contentHtml);
      else content = JSON.stringify(data, null, 2);
      try {
        fs.writeFileSync(fp, content, "utf-8");
      } catch (e) { /* 静默失败，下次手动保存时会提示 */ }
    }
  }, 800);
}

function loadDocToEditor(doc) {
  if (doc.contentDelta && doc.contentDelta.ops) {
    quill.setContents(doc.contentDelta);
  } else if (doc.content) {
    quill.clipboard.dangerouslyPasteHTML(doc.content);
  } else {
    quill.setText("");
  }
}

function refreshFileList(keyword = "") {
  const container = document.getElementById("fileList");
  container.innerHTML = "";
  const keys = Object.keys(localStorage).filter(k => k.startsWith("doc_"));
  const docs = keys.map(k => {
    const doc = JSON.parse(localStorage.getItem(k));
    return { id: k, title: doc.title, updatedAt: doc.updatedAt || 0, doc, filePath: doc.filePath };
  });
  docs.sort((a, b) => b.updatedAt - a.updatedAt);
  const filtered = keyword ? docs.filter(d => d.title.toLowerCase().includes(keyword.toLowerCase())) : docs;

  for (const item of filtered) {
    const div = document.createElement("div");
    div.className = "file-item";
    if (currentDocId === item.id) div.classList.add("active");

    const infoDiv = document.createElement("div");
    infoDiv.style.cssText = "flex:1;min-width:0;overflow:hidden";

    const titleSpan = document.createElement("span");
    titleSpan.className = "file-title";
    titleSpan.textContent = item.title;
    titleSpan.addEventListener("click", () => {
      currentDocId = item.id;
      loadDocToEditor(item.doc);
      refreshFileList(keyword);
      showToast(`打开：${item.title}`);
    });
    infoDiv.appendChild(titleSpan);

    if (item.filePath) {
      const pathHint = document.createElement("div");
      pathHint.style.cssText = "font-size:11px;color:#94a3b8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
      pathHint.textContent = item.filePath;
      infoDiv.appendChild(pathHint);
    }

    const delSpan = document.createElement("span");
    delSpan.className = "file-del";
    delSpan.title = "删除";
    delSpan.textContent = "🗑️";
    delSpan.addEventListener("click", (e) => {
      e.stopPropagation();
      if (confirm(`删除文档"${item.title}"？`)) {
        localStorage.removeItem(item.id);
        if (currentDocId === item.id) {
          currentDocId = null;
          quill.setText("");
        }
        refreshFileList(keyword);
        showToast("已删除");
      }
    });

    div.appendChild(infoDiv);
    div.appendChild(delSpan);
    container.appendChild(div);
  }
  if (filtered.length === 0 && keyword) {
    container.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8;">无匹配文档</div>';
  }
}

function createNewDoc() {
  const id = "doc_" + Date.now();
  const defaultTitle = `笔记 ${new Date().toLocaleString()}`;
  const newDoc = {
    title: defaultTitle,
    contentDelta: { ops: [{ insert: "\n" }] },
    updatedAt: Date.now(),
    filePath: null
  };
  localStorage.setItem(id, JSON.stringify(newDoc));
  currentDocId = id;
  loadDocToEditor(newDoc);
  refreshFileList();
  showToast("新文档已创建");
}

// ======================== AI 选区菜单 ========================
const aiMenu = document.getElementById("aiMenu");

async function handleAIAction(action) {
  let range = quill.getSelection();
  // 按钮点击时编辑器可能已失焦，回退到缓存的选区
  if ((!range || range.length === 0) && lastSelection) {
    range = lastSelection;
  }
  if (!range || range.length === 0) {
    showToast("请先选中文本", true);
    return;
  }
  const selectedText = quill.getText(range.index, range.length);
  if (!selectedText.trim()) return;

  const actionNames = { polish: "润色", summary: "总结", expand: "扩写", shorten: "缩短", translate: "自动翻译", pinyin: "拼音标注" };
  showToast(`🤖 AI 正在${actionNames[action] || "处理"}...`);
  try {
    let prompt = "", result = "";
    switch (action) {
      case "polish":
        prompt = `请润色以下文本，使其表达更流畅、更专业，只输出润色后的结果：\n\n${selectedText}`;
        result = await callAI(prompt, "你是一个专业的中文写作助手，擅长文字润色。");
        quill.deleteText(range.index, range.length);
        quill.insertText(range.index, result);
        quill.setSelection(range.index, result.length);
        break;
      case "summary":
        prompt = `请用一两句话总结以下内容的核心要点：\n\n${selectedText}`;
        result = await callAI(prompt, "你是一个善于提炼核心信息的助手。");
        quill.insertText(range.index + range.length, `\n\n📌 总结：${result}\n\n`);
        break;
      case "expand":
        prompt = `请扩写以下内容，使表达更丰富、更有深度，保持原有风格：\n\n${selectedText}`;
        result = await callAI(prompt, "你是一个擅长内容扩写的专业写作助手。");
        quill.insertText(range.index + range.length, `\n\n📖 扩写：${result}\n\n`);
        break;
      case "shorten":
        prompt = `请将以下文本压缩精简，保留核心信息，语言更精炼：\n\n${selectedText}`;
        result = await callAI(prompt, "你是一个善于精炼文字的专业编辑。");
        quill.deleteText(range.index, range.length);
        quill.insertText(range.index, result);
        quill.setSelection(range.index, result.length);
        break;
      case "translate": {
        const isZh = detectLanguage(selectedText) === "zh";
        prompt = isZh
          ? `请将以下中文翻译为英文：\n\n${selectedText}`
          : `请将以下英文翻译为中文：\n\n${selectedText}`;
        const sysMsg = isZh ? "你是一个专业的中英翻译助手，只输出英文翻译。" : "你是一个专业的英中翻译助手，只输出中文翻译。";
        const label = isZh ? "英文翻译" : "中文翻译";
        result = await callAI(prompt, sysMsg);
        quill.insertText(range.index + range.length, `\n\n🌐 ${label}：\n${result}\n\n`);
        break;
      }
      case "pinyin": {
        if (typeof pinyinPro === "undefined") {
          showToast("拼音库未加载，请检查网络后刷新", true);
          return;
        }
        const pyArray = pinyinPro.pinyin(selectedText, { toneType: "symbol", type: "array" });
        let rubyHtml = "";
        for (let i = 0; i < selectedText.length; i++) {
          const ch = selectedText[i];
          const py = pyArray[i] || "";
          if (/[一-鿿㐀-䶿]/.test(ch) && py) {
            rubyHtml += `<ruby>${ch}<rt>${py}</rt></ruby>`;
          } else if (ch.match(/\s+/)) {
            rubyHtml += ch;
          } else {
            rubyHtml += ch;
          }
        }
        quill.deleteText(range.index, range.length);
        quill.clipboard.dangerouslyPasteHTML(range.index, rubyHtml);
        quill.setSelection(range.index, rubyHtml.length);
        break;
      }
    }
    saveCurrentDoc();
  } catch (err) {
    // 错误已在callAI中处理
  } finally {
    aiMenu.style.display = "none";
  }
}

// 显示 AI 菜单
document.addEventListener("mouseup", (e) => {
  setTimeout(() => {
    if (aiMenu.contains(e.target)) return;
    const range = quill.getSelection();
    if (range && range.length > 0) {
      const bounds = quill.getBounds(range.index, 0);
      const editorRect = document.getElementById("editor").getBoundingClientRect();
      const top = Math.max(editorRect.top + 10, bounds.top + editorRect.top - 48);
      const left = Math.min(bounds.left + editorRect.left, editorRect.right - 350);
      aiMenu.style.display = "flex";
      aiMenu.style.top = `${top}px`;
      aiMenu.style.left = `${left}px`;
    } else {
      aiMenu.style.display = "none";
    }
  }, 10);
});

document.querySelectorAll("#aiMenu button").forEach(btn => {
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    handleAIAction(btn.getAttribute("data-action"));
  });
});

document.addEventListener("mousedown", (e) => {
  if (!aiMenu.contains(e.target)) {
    aiMenu.style.display = "none";
  }
});

// ======================== 聊天 ========================
const CHAT_SYSTEM_PROMPT = [
  "你是一个友好、热情的AI写作助手，名叫「小笔」。",
  "你的回复风格：",
  "- 语气亲切自然，像朋友聊天一样",
  "- 回答简洁有力，不啰嗦",
  "- 善于引导用户表达想法",
  "- 如果用户问写作相关问题，主动给出实用建议",
  "- 适当使用表情符号增加亲和力 (如 ✨📝💡)",
  "- 始终用中文回复"
].join("\n");

async function sendChatMessage() {
  if (isChatLoading) return;
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text) return;
  addChatMessage(text, "user");
  input.value = "";
  isChatLoading = true;
  const sendBtn = document.getElementById("sendBtn");
  sendBtn.disabled = true;
  try {
    const reply = await callAI(text, CHAT_SYSTEM_PROMPT);
    addChatMessage(reply, "ai");
  } catch {
    addChatMessage("😅 抱歉，AI 暂时无法响应，请稍后重试或检查网络。", "error");
  } finally {
    isChatLoading = false;
    sendBtn.disabled = false;
    input.focus();
  }
}

function addChatMessage(text, type) {
  const container = document.getElementById("chatBox");
  const msgDiv = document.createElement("div");
  msgDiv.className = `msg ${type}`;
  msgDiv.innerHTML = text.replace(/\n/g, "<br>");
  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
}

// ======================== Markdown 预览 ========================
const editorDiv = document.getElementById("editor");
const previewDiv = document.getElementById("markdownPreview");
const turndownService = new TurndownService();

async function toggleMarkdown() {
  if (!isPreviewMode) {
    const html = quill.root.innerHTML;
    const markdown = turndownService.turndown(html);
    previewDiv.innerText = markdown;
    editorDiv.style.display = "none";
    previewDiv.style.display = "block";
    isPreviewMode = true;
    showToast("Markdown 预览模式，点击按钮返回编辑");
  } else {
    editorDiv.style.display = "block";
    previewDiv.style.display = "none";
    isPreviewMode = false;
  }
}

// ======================== 键盘快捷键 ========================
document.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;

  if (e.key === "s" && e.shiftKey) {
    // Ctrl+Shift+S → 另存为
    e.preventDefault();
    saveDocumentAs();
  } else if (e.key === "s") {
    // Ctrl+S → 快速保存
    e.preventDefault();
    saveDocument();
  } else if (e.key === "o") {
    // Ctrl+O → 打开文件
    e.preventDefault();
    openDocument();
  }
});

// ======================== 事件绑定 ========================
quill.on("text-change", () => {
  if (currentDocId) debounceSave();
});

// 缓存选区，防止点击工具栏/AI菜单按钮时编辑器失焦导致 getSelection() 返回 null
quill.on("selection-change", (range) => {
  if (range && range.length > 0) {
    lastSelection = { index: range.index, length: range.length };
  }
});

document.getElementById("searchInput").addEventListener("input", (e) => {
  refreshFileList(e.target.value);
});
document.getElementById("newDocBtn").addEventListener("click", createNewDoc);
document.getElementById("sendBtn").addEventListener("click", sendChatMessage);
document.getElementById("chatInput").addEventListener("keypress", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
});
document.getElementById("markdownBtn").addEventListener("click", toggleMarkdown);
document.getElementById("topPolishBtn").addEventListener("click", () => handleAIAction("polish"));
document.getElementById("topSummaryBtn").addEventListener("click", () => handleAIAction("summary"));
document.getElementById("topExpandBtn").addEventListener("click", () => handleAIAction("expand"));
document.getElementById("topTranslateBtn").addEventListener("click", () => handleAIAction("translate"));
document.getElementById("topPinyinBtn").addEventListener("click", () => handleAIAction("pinyin"));

// 保存/导出按钮
const saveBtn = document.getElementById("saveBtn");
const exportMenu = document.getElementById("exportMenu");
if (saveBtn) saveBtn.addEventListener("click", () => saveDocument());
if (exportMenu) {
  exportMenu.addEventListener("click", (e) => {
    const exportDropdown = document.getElementById("exportDropdown");
    exportDropdown.style.display = exportDropdown.style.display === "flex" ? "none" : "flex";
  });
  document.querySelectorAll("#exportDropdown button").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const fmt = btn.getAttribute("data-format");
      if (fmt === "json") saveDocumentAs();
      else if (fmt === "md") exportMarkdown();
      else if (fmt === "txt") exportTxt();
      else if (fmt === "html") exportHtml();
      else if (fmt === "pdf") exportPdf();
      else if (fmt === "doc") exportDoc();
      document.getElementById("exportDropdown").style.display = "none";
    });
  });
}
// 点击外部关闭导出菜单
document.addEventListener("click", (e) => {
  const dd = document.getElementById("exportDropdown");
  if (dd && !dd.contains(e.target) && e.target !== document.getElementById("exportMenu")) {
    dd.style.display = "none";
  }
});

// ======================== 左右面板拖拽伸缩 ========================
function makeResizable(barId, panelId, minW, maxW) {
  const bar = document.getElementById(barId);
  const panel = document.getElementById(panelId);
  if (!bar || !panel) return;
  let dragging = false;
  let startX, startWidth;

  bar.addEventListener("mousedown", (e) => {
    dragging = true;
    startX = e.pageX;
    startWidth = panel.getBoundingClientRect().width;
    e.preventDefault();
    e.stopPropagation();
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const dx = e.pageX - startX;
    const delta = barId === "resizeBarRight" ? -dx : dx;
    let newWidth = startWidth + delta;
    newWidth = Math.min(maxW, Math.max(minW, newWidth));
    panel.style.width = newWidth + "px";
  }, true);

  document.addEventListener("mouseup", () => {
    if (dragging) {
      dragging = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
  }, true);
}

makeResizable("resizeBarLeft", "sidebar", 180, 450);
makeResizable("resizeBarRight", "aiPanel", 260, 500);

window.addEventListener("beforeunload", () => {
  if (saveTimer) clearTimeout(saveTimer);
  saveCurrentDoc();
});

// ======================== 初始化 ========================
function init() {
  const existing = Object.keys(localStorage).filter(k => k.startsWith("doc_"));
  if (existing.length === 0) {
    createNewDoc();
  } else {
    const latest = existing.sort((a, b) => {
      const da = JSON.parse(localStorage.getItem(a));
      const db = JSON.parse(localStorage.getItem(b));
      return (db.updatedAt || 0) - (da.updatedAt || 0);
    })[0];
    currentDocId = latest;
    loadDocToEditor(JSON.parse(localStorage.getItem(latest)));
  }
  refreshFileList();
}
init();

// ======================== API Helpers ========================
const API_BASE = 'http://127.0.0.1:8765';

// Data API
async function apiGetStocks() {
  const res = await fetch(`${API_BASE}/api/data/stocks`);
  return res.json();
}

async function apiRefreshStocks() {
  const res = await fetch(`${API_BASE}/api/data/stocks/refresh`, { method: 'POST' });
  return res.json();
}

async function apiGetDaily(symbol, start, end) {
  const url = new URL(`${API_BASE}/api/data/daily/${symbol}`);
  if (start) url.searchParams.set('start', start);
  if (end) url.searchParams.set('end', end);
  const res = await fetch(url);
  return res.json();
}

async function apiDownload(symbols, startDate, endDate) {
  const res = await fetch(`${API_BASE}/api/data/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbols, start_date: startDate, end_date: endDate }),
  });
  return res.json();
}

// Strategy API
async function apiGetTemplates() {
  const res = await fetch(`${API_BASE}/api/strategy/templates`);
  return res.json();
}

// Backtest API
async function apiRunBacktest(config) {
  const res = await fetch(`${API_BASE}/api/backtest/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return res.json();
}

async function apiGetBacktestResult(id) {
  const res = await fetch(`${API_BASE}/api/backtest/result/${id}`);
  return res.json();
}

// Sentiment API
async function apiGetSentiment() {
  const res = await fetch(`${API_BASE}/api/sentiment/current`);
  return res.json();
}

// Health check
async function apiHealth() {
  const res = await fetch(`${API_BASE}/api/health`);
  return res.json();
}

console.log('A股交易工具 API helpers loaded');
