/* 临时截图脚本：puppeteer-core + 本机 Chrome，逐页截图供设计验证。 */
import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";

const BASE = "http://localhost:3000";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const OUT = "shots";
mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getToken(username, password) {
  const res = await fetch("http://127.0.0.1:8001/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const j = await res.json();
  return j.access_token;
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--window-size=1440,900", "--force-device-scale-factor=1.5"],
  defaultViewport: { width: 1440, height: 900, deviceScaleFactor: 1.5 },
});

async function shot(name, path, { token, dark = false, wait = 1200 } = {}) {
  const page = await browser.newPage();
  if (dark) await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "dark" }]);
  if (token) {
    await page.goto(BASE + "/login", { waitUntil: "domcontentloaded" });
    await page.evaluate((t) => localStorage.setItem("token", t), token);
  }
  await page.goto(BASE + path, { waitUntil: "networkidle0", timeout: 60000 }).catch(() => {});
  await sleep(wait);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  await page.close();
  console.log("shot:", name);
}

try {
  const token = await getToken("smoke_fin_5499", "test123456");
  const m7token = await getToken("smoke_m7_7955", "test123456");

  await shot("landing", "/", { wait: 2500 });
  await shot("landing-dark", "/", { dark: true, wait: 2500 });
  await shot("login", "/login", { wait: 2000 });
  await shot("register", "/register");
  await shot("dashboard", "/dashboard", { token });
  await shot("history", "/history", { token });
  await shot("interview-new", "/interview/new", { token });
  await shot("resume-upload", "/resume/upload", { token });
  await shot("chat-finished", "/interview/9", { token });
  await shot("chat-active", "/interview/8", { token: m7token });
  await shot("report", "/report/9", { token });
  await shot("report-dark", "/report/9", { token, dark: true });
  console.log("ALL DONE");
} finally {
  await browser.close();
}
