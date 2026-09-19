/** 面试进行中给候选人看的错误，不展示 Python / 栈信息。 */

const INTERNAL =
  /not defined|traceback|nameerror|typeerror|keyerror|attributeerror|sqlalchemy|get_redis|nonetype|internal server|file ["']|psycopg|redis/i;

export function friendlyInterviewError(raw: string): string {
  const text = (raw || "").trim();
  if (!text) return "发送失败，请再试一次";
  if (INTERNAL.test(text) || text.length > 80) return "发送失败，请再试一次";
  if (/[\\/"']/.test(text) && !/^(会话不存在|面试已结束|未登录|回答不能为空)/.test(text)) {
    return "发送失败，请再试一次";
  }
  return text;
}
