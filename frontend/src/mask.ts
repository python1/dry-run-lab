/** Hide passwords, secrets, and SNMP communities in the page the user can screenshot. */

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
  out = out.replace(/\b(auth\s+(?:md5|sha|sha256|sha384|sha512)\s+)(\S+)/gi, `$1${SECRET}`);
  out = out.replace(/\b(priv\s+(?:des|3des|aes)(?:\s+\d+)?\s+)(\S+)/gi, `$1${SECRET}`);
  return out;
}
