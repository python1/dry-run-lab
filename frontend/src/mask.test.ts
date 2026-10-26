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
assert.equal(maskSecretsDefault(null), true);
assert.equal(maskSecretsDefault("on"), true);
assert.equal(maskSecretsDefault("off"), false);
console.log("mask ok");
