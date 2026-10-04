import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, utimesSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { resolvePython, newestSource } from "./start.mjs";

test("standard venv, Conda layout and explicit interpreter selection", () => {
  const root = mkdtempSync(join(tmpdir(), "ftl launch spaces "));
  try {
    mkdirSync(join(root, ".venv", "Scripts"), { recursive: true });
    const standard = join(root, ".venv", "Scripts", "python.exe");
    const conda = join(root, ".venv", "python.exe");
    writeFileSync(standard, "fixture");
    writeFileSync(conda, "fixture");
    assert.equal(resolvePython(root, undefined, () => true), standard);
    assert.equal(resolvePython(root, undefined, (path) => path === conda), conda);
    assert.equal(resolvePython(root, conda, () => true), conda);
    assert.throws(() => resolvePython(root, join(root, "missing.exe"), () => true), /Python is unavailable/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("source edits trigger rebuild checks; generated output does not", () => {
  const root = mkdtempSync(join(tmpdir(), "ftl build check "));
  try {
    mkdirSync(join(root, "src"));
    mkdirSync(join(root, "dist"));
    const source = join(root, "src", "App.tsx");
    const output = join(root, "dist", "index.html");
    writeFileSync(source, "source");
    writeFileSync(output, "generated");
    utimesSync(source, new Date(1000), new Date(1000));
    utimesSync(output, new Date(9000), new Date(9000));
    assert.equal(newestSource(root), 1000);
    utimesSync(source, new Date(10000), new Date(10000));
    assert.equal(newestSource(root), 10000);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
