/** 浏览器麦克风可用性（getUserMedia / Web Speech 均需安全上下文）。 */

export function canUseMicrophone(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia);
}

export function micBlockedMessage(): string {
  if (typeof window === "undefined") return "";
  if (!window.isSecureContext) {
    return "当前为 HTTP 访问，浏览器不允许麦克风。请使用 HTTPS 域名访问，或先用文字输入。";
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return "当前浏览器不支持麦克风，请改用文字输入。";
  }
  return "无法访问麦克风，请在浏览器地址栏允许麦克风权限。";
}
