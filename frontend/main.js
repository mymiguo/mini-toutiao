const { app, BrowserWindow, Menu, ipcMain, dialog } = require("electron");
const path = require("path");
const fs = require("fs");

Menu.setApplicationMenu(null);

// —— IPC：保存对话框 ——
ipcMain.handle("show-save-dialog", async (_event, defaultPath, filters) => {
  const win = BrowserWindow.getFocusedWindow();
  return dialog.showSaveDialog(win, {
    title: "保存文档",
    defaultPath: defaultPath || "untitled",
    filters: filters || [
      { name: "JSON 文档 (保留格式)", extensions: ["json"] },
      { name: "所有文件", extensions: ["*"] }
    ]
  });
});

// —— IPC：打开对话框 ——
ipcMain.handle("show-open-dialog", async () => {
  const win = BrowserWindow.getFocusedWindow();
  return dialog.showOpenDialog(win, {
    title: "打开文档",
    filters: [
      { name: "支持的文档", extensions: ["json", "md", "html", "txt"] },
      { name: "所有文件", extensions: ["*"] }
    ],
    properties: ["openFile"]
  });
});

// —— IPC：导出 PDF（用隐藏独立窗口渲染文档内容，仅导出文档不含 UI） ——
ipcMain.handle("export-pdf", async (_event, htmlContent, filePath) => {
  return new Promise((resolve) => {
    const pdfWin = new BrowserWindow({
      width: 794,   // A4 @ 96dpi
      height: 1123,
      show: false,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true
      }
    });

    // 用 data URL 加载 HTML 内容，无需写临时文件
    const encoded = Buffer.from(htmlContent, "utf-8").toString("base64");
    pdfWin.loadURL("data:text/html;charset=utf-8;base64," + encoded);

    pdfWin.webContents.on("did-finish-load", async () => {
      try {
        // 等待字体渲染完成
        await new Promise(r => setTimeout(r, 500));
        const pdfData = await pdfWin.webContents.printToPDF({
          printBackground: true,
          pageSize: "A4",
          margins: { top: "20mm", bottom: "20mm", left: "20mm", right: "20mm" }
        });
        fs.writeFileSync(filePath, pdfData);
        resolve({ success: true });
      } catch (err) {
        resolve({ success: false, error: err.message });
      } finally {
        pdfWin.close();
      }
    });

    pdfWin.webContents.on("did-fail-load", (_e, _code, desc) => {
      resolve({ success: false, error: desc });
      if (!pdfWin.isDestroyed()) pdfWin.close();
    });
  });
});

async function checkBackend() {
  try {
    const health = await fetch('http://127.0.0.1:8765/api/health').then(r => r.json());
    console.log('Backend status:', health);
    return health.status === 'ok';
  } catch (e) {
    console.error('Backend not available:', e.message);
    return false;
  }
}

function createWindow() {
  const iconPath = path.join(__dirname, "assets", "icon.ico");
  const browserOptions = {
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webSecurity: false,
      allowRunningInsecureContent: false
    },
    show: false,
    backgroundColor: "#f5f7fb"
  };

  if (fs.existsSync(iconPath)) {
    browserOptions.icon = iconPath;
  }

  const win = new BrowserWindow(browserOptions);
  win.loadFile("index.html");

  win.once("ready-to-show", () => {
    win.show();
  });

  win.on("closed", () => {});
}

const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.whenReady().then(async () => {
    await checkBackend();
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
