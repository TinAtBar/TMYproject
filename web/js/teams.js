// R5-F: Microsoft-Teams-Deeplinks (öffnen per <a target=_blank>; Desktop-Edge übergibt an msteams:)
import { h, icon } from './util.js';

const enc = encodeURIComponent;
const liste = e => (Array.isArray(e) ? e : String(e || '').split(/[;,\s]+/)).map(x => String(x || '').trim()).filter(x => x.includes('@'));

/** Chat-Deeplink: teamsChat(['a@x.de'], 'Thema', 'Nachricht') → URL */
export function teamsChat(emails, topic, message) {
  const p = [`users=${liste(emails).map(enc).join(',')}`];
  if (topic) p.push('topicName=' + enc(topic));
  if (message) p.push('message=' + enc(message));
  return 'https://teams.microsoft.com/l/chat/0/0?' + p.join('&');
}
/** Neue Besprechung planen (Betreff + Teilnehmer vorbelegt) → URL */
export function teamsBesprechungNeu(subject, attendees) {
  const p = ['subject=' + enc(subject || '')];
  const a = liste(attendees);
  if (a.length) p.push('attendees=' + a.map(enc).join(','));
  return 'https://teams.microsoft.com/l/meeting/new?' + p.join('&');
}
/** Link-Knopf (<a target=_blank>) */
export function teamsKnopf(href, label = 'Teams', cls = 'btn btn-sm') {
  if (!istTeamsLink(href)) return null; // nie javascript:/fremde Hosts als href
  return h('a', { class: cls + ' teams-btn', href, target: '_blank', rel: 'noopener', title: label }, icon('chat', 16), label);
}
export const istTeamsLink = s => /^(https:\/\/teams\.microsoft\.com\/|msteams:)[^\s<>"']*$/i.test(String(s || '').trim());
