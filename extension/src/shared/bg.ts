// Message the background worker; never throws (a dead extension context becomes a normal error reply).
export interface Reply { ok: boolean; error?: string; notConnected?: boolean; [k: string]: any }
export const send = (msg: object): Promise<Reply> =>
  chrome.runtime.sendMessage(msg).then((r) => r ?? { ok: false, error: 'No reply' }, (e) => ({ ok: false, error: e instanceof Error ? e.message : 'Failed' }));
export const WEB_APP = 'https://reelpicks-32e42.web.app/';
