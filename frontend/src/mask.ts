/** Hide passwords, secrets, SNMP communities, and authentication keys in the page the user can screenshot. */

const SECRET = "********";

export function maskSecretsDefault(stored: string | null): boolean {
  return stored !== "off";
}

export function maskConfig(text: string): string {
  return text.split("\n").map(maskLine).join("\n");
}

function maskLine(line: string): string {
  let out = line;
  out = out.replace(/^(\s*enable\s+(?:secret|password)\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(
    /^(\s*username\s+\S+.*?(\s+(?:secret|password)\s+)(?:\d+\s+)?)(\S+)/i,
    `$1${SECRET}`,
  );
  out = out.replace(/^(\s*snmp-server\s+community\s+)(\S+)/i, `$1${SECRET}`);
  out = out.replace(
    /^(\s*snmp-server\s+host\s+\S+(?:\s+(?:version|vrf|informs|traps|udp-port)\s+\S+)*)\s+(\S+)/i,
    `$1 ${SECRET}`,
  );
  out = out.replace(/^(\s*(?:password|secret)\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(/^(\s*key-string\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(
    /^(\s*(?:tacacs-server|radius-server|ip\s+radius\s+source-interface)?\s*(?:tacacs-server|radius-server)\s+key\s+(?:\d+\s+)?)(\S+)/i,
    `$1${SECRET}`,
  );
  out = out.replace(/^(\s*(?:tacacs-server|radius-server)\s+key\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(/^(\s*(?:tacacs-server|radius-server)\s+host\b.*\bkey\s+(?:\d+\s+)?)(\S+)\s*$/i, `$1${SECRET}`);
  out = out.replace(/^(\s*ip\s+ospf\s+authentication-key\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(/^(\s*ip\s+ospf\s+message-digest-key\s+\d+\s+md5\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(/^(\s*neighbor\s+\S+\s+password\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(/^(\s*ntp\s+authentication-key\s+\d+\s+\S+\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(/^(\s*crypto\s+isakmp\s+key\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(/^(\s*pre-shared-key\s+address\s+\S+\s+key\s+(?:\d+\s+)?)(\S+)/i, `$1${SECRET}`);
  out = out.replace(/^(\s*pre-shared-key\s+local\s+)(\S+)(\s+remote\s+)(\S+)/i, `$1${SECRET}$3${SECRET}`);
  out = out.replace(/^(\s*pre-shared-key\s+)(?!address\b|local\b)(\S+)/i, `$1${SECRET}`);
  out = out.replace(
    /^(\s*standby\s+\d+\s+authentication(?:\s+md5)?(?:\s+(?:key-string|text))?\s+(?:\d+\s+)?)(\S+)/i,
    `$1${SECRET}`,
  );
  out = out.replace(/^(\s*key\s+)(?!chain\b)(?:([0-7])\s+)?(\S+)/i, (full, prefix: string, enc: string | undefined, token: string) => {
    if (enc === undefined && /^\d+$/.test(token)) return full;
    return `${prefix}${enc !== undefined ? `${enc} ` : ""}${SECRET}`;
  });
  out = out.replace(/\b(auth\s+(?:md5|sha|sha256|sha384|sha512)\s+)(\S+)/gi, `$1${SECRET}`);
  out = out.replace(/\b(priv\s+(?:des|3des|aes)(?:\s+\d+)?\s+)(\S+)/gi, `$1${SECRET}`);
  return out;
}
