import assert from "node:assert/strict";
import { maskConfig, maskSecretsDefault } from "./mask.ts";

const sample = [
  "enable secret 5 $1$abcdefgh",
  "enable password cisco",
  "username admin privilege 15 secret 9 verysecret",
  "snmp-server community public RO",
  "snmp-server host 10.1.1.1 version 2c private",
  " password 7 0822455D0A16",
  " key-string s3cretKey",
  "tacacs-server key 7 hiddenkey",
  " description public facing link",
].join("\n");

const masked = maskConfig(sample);
for (const secret of ["$1$abcdefgh", "cisco", "verysecret", "public RO", "private", "0822455D0A16", "s3cretKey", "hiddenkey"]) {
  assert.equal(masked.includes(secret), false, secret);
}
assert.equal(masked.includes("enable secret"), true);
assert.equal(masked.includes("snmp-server community"), true);
assert.equal(masked.includes("public facing"), true);

const keys = [
  " ip ospf authentication-key 7 ospfSecret",
  " neighbor 10.1.1.1 password 7 bgpSecret",
  "ntp authentication-key 1 md5 ntpSecret",
  "crypto isakmp key isakmpSecret address 10.9.9.9",
  " standby 1 authentication md5 key-string 7 hsrpSecret",
  "tacacs-server key 7 oldTacacs",
  "radius-server key oldRadius",
  " key 7 newTacacs",
  "key chain OSPF",
  " key 1",
].join("\n");
const hidden = maskConfig(keys);
for (const secret of ["ospfSecret", "bgpSecret", "ntpSecret", "isakmpSecret", "hsrpSecret", "oldTacacs", "oldRadius", "newTacacs"]) {
  assert.equal(hidden.includes(secret), false, secret);
}
assert.equal(hidden.includes("ip ospf authentication-key"), true);
assert.equal(hidden.includes("neighbor 10.1.1.1 password"), true);
assert.equal(hidden.includes("ntp authentication-key"), true);
assert.equal(hidden.includes("crypto isakmp key"), true);
assert.equal(hidden.includes("standby 1 authentication"), true);
assert.equal(hidden.includes("tacacs-server key"), true);
assert.equal(hidden.includes("radius-server key"), true);
assert.equal(hidden.includes("key chain OSPF"), true);
assert.match(hidden, /^ key 1$/m);
assert.equal(maskSecretsDefault(null), true);
assert.equal(maskSecretsDefault("on"), true);
assert.equal(maskSecretsDefault("off"), false);
console.log("mask ok");
