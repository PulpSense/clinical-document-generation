#!/usr/bin/env node
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

async function loadPackage(name) {
  try {
    const mod = await import(name);
    return mod.default ?? mod;
  } catch (error) {
    const packageDir = process.env.CLINICAL_DOC_NODE_PACKAGE_DIR;
    if (!packageDir) {
      throw new Error(
        `Missing Node dependency "${name}". Run "cd scripts && npm install", ` +
          "or set CLINICAL_DOC_NODE_PACKAGE_DIR to a directory containing node_modules."
      );
    }
    const packageJson = path.join(path.resolve(packageDir), "package.json");
    const requireFromPackageDir = createRequire(packageJson);
    return requireFromPackageDir(name);
  }
}

const Docxtemplater = await loadPackage("docxtemplater");
const PizZip = await loadPackage("pizzip");

const STANDARD = {
  reference: "reference/study.reference.json",
  xmlTemplate: "templates/study.template.xml",
  xmlOutput: "output/study.xml",
  report: "logs/generation-report.json"
};

const DOCX_OUTPUTS = [
  { key: "protocol_docx", template: "templates/protocol.template.docx", output: "output/protocol.docx" },
  { key: "icf_docx", template: "templates/icf.template.docx", output: "output/icf.docx" },
  { key: "short_docx", template: "templates/short.template.docx", output: "output/short.docx" },
  { key: "main_docx", template: "templates/main.template.docx", output: "output/main.docx" }
];

const XML_OUTPUT = { key: "xml", template: STANDARD.xmlTemplate, output: STANDARD.xmlOutput };

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) {
      throw new Error(`Unexpected argument: ${key}`);
    }
    const name = key.slice(2);
    const value = argv[i + 1];
    if (!value || value.startsWith("--")) {
      args[name] = true;
    } else {
      args[name] = value;
      i += 1;
    }
  }
  return args;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function ensureDir(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function relToRun(filePath, runDir) {
  const relative = path.relative(runDir, filePath);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    return path.basename(filePath);
  }
  return relative.split(path.sep).join("/");
}

function getPath(data, dottedPath) {
  if (!dottedPath) return undefined;
  const parts = dottedPath.split(".");
  let current = data;
  for (const part of parts) {
    if (current == null) return undefined;
    current = current[part];
  }
  return current;
}

function makeDocxParser(rootData) {
  return function parser(tag) {
    return {
      get(scope, context) {
        if (tag === ".") return scope;
        let value = getPath(scope, tag);
        if (value !== undefined) return value;
        const scopeList = Array.isArray(context?.scopeList) ? context.scopeList : [];
        for (let i = scopeList.length - 1; i >= 0; i -= 1) {
          value = getPath(scopeList[i], tag);
          if (value !== undefined) return value;
        }
        value = getPath(rootData, tag);
        return value === undefined ? "" : value;
      }
    };
  };
}

function xmlEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function renderTextTemplate(template, rootData, localData = rootData) {
  const blockRe = /\{#([A-Za-z0-9_.\-\[\]\(\)&]+)\}([\s\S]*?)\{\/\1\}/g;
  let rendered = template.replace(blockRe, (_match, blockPath, body) => {
    const value = getPath(localData, blockPath) ?? getPath(rootData, blockPath);
    if (Array.isArray(value)) {
      return value.map((item) => renderTextTemplate(body, rootData, item)).join("");
    }
    if (value && typeof value === "object") {
      return renderTextTemplate(body, rootData, value);
    }
    if (value) {
      return renderTextTemplate(body, rootData, localData);
    }
    return "";
  });

  const varRe = /\{([A-Za-z0-9_.\-\[\]\(\)&]+)\}/g;
  rendered = rendered.replace(varRe, (_match, varPath) => {
    const value = getPath(localData, varPath) ?? getPath(rootData, varPath);
    if (value == null) return "";
    if (typeof value === "object") return xmlEscape(JSON.stringify(value));
    return xmlEscape(value);
  });
  return rendered;
}

function prsCounts(data) {
  if (String(data?.__xml_profile ?? data?.regulatory?.xml_profile ?? "") !== "clinicaltrials-prs") {
    return null;
  }
  const counts = data?.__prs_counts;
  if (!counts || typeof counts !== "object" || Array.isArray(counts)) return null;
  return counts;
}

function renumberPrsBlock(block, tagName, fromIndex, toIndex) {
  if (tagName === "primary_outcome") {
    return block.replaceAll("primaryOutcome", `primaryOutcome${toIndex}`);
  }
  const baseByTag = {
    intervention: "intervention",
    arm_group: "armGroup",
    secondary_outcome: "secondaryOutcome",
    other_outcome: "otherOutcome"
  };
  const base = baseByTag[tagName];
  if (!base) return block;
  return block.replaceAll(`${base}${fromIndex}`, `${base}${toIndex}`);
}

function adjustPrsRepeatedBlocks(template, data) {
  const counts = prsCounts(data);
  if (!counts) return template;

  let adjusted = template;
  const tags = ["intervention", "arm_group", "primary_outcome", "secondary_outcome", "other_outcome"];
  for (const tagName of tags) {
    const count = Number.isFinite(Number(counts[tagName])) ? Math.max(0, Number(counts[tagName])) : null;
    if (count == null) continue;
    const blockRe = new RegExp(`\\n?\\s*<${tagName}>[\\s\\S]*?<\\/${tagName}>`, "g");
    const matches = Array.from(adjusted.matchAll(blockRe));
    if (matches.length === 0) continue;

    if (count <= matches.length) {
      let seen = 0;
      adjusted = adjusted.replace(blockRe, (match) => {
        seen += 1;
        return seen <= count ? match : "";
      });
      continue;
    }

    const last = matches[matches.length - 1];
    const lastBlock = last[0];
    const insertAt = Number(last.index) + lastBlock.length;
    let extra = "";
    for (let nextIndex = matches.length + 1; nextIndex <= count; nextIndex += 1) {
      extra += renumberPrsBlock(lastBlock, tagName, matches.length, nextIndex);
    }
    adjusted = adjusted.slice(0, insertAt) + extra + adjusted.slice(insertAt);
  }
  return adjusted;
}

function unresolvedInText(text) {
  const matches = text.match(/\{[#/^]?[A-Za-z_][A-Za-z0-9_.\-\[\]\(\)&]*\}/g);
  if (!matches) return [];
  const guidRe = /^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$/;
  return Array.from(new Set(matches.filter((match) => !guidRe.test(match)))).sort();
}

function unresolvedInDocx(filePath) {
  const content = fs.readFileSync(filePath);
  const zip = new PizZip(content);
  const unresolved = new Set();
  for (const fileName of Object.keys(zip.files)) {
    if (!fileName.startsWith("word/") || !fileName.endsWith(".xml")) continue;
    const text = zip.file(fileName)?.asText() ?? "";
    for (const item of unresolvedInText(text)) unresolved.add(item);
  }
  return Array.from(unresolved).sort();
}

function renderDocx(templatePath, outputPath, data) {
  const content = fs.readFileSync(templatePath, "binary");
  const zip = new PizZip(content);
  const doc = new Docxtemplater(zip, {
    paragraphLoop: true,
    linebreaks: true,
    parser: makeDocxParser(data),
    nullGetter: () => ""
  });
  doc.render(data);
  const buffer = doc.getZip().generate({
    type: "nodebuffer",
    compression: "DEFLATE"
  });
  ensureDir(outputPath);
  fs.writeFileSync(outputPath, buffer);
  return unresolvedInDocx(outputPath);
}

function renderXml(templatePath, outputPath, data) {
  const template = adjustPrsRepeatedBlocks(fs.readFileSync(templatePath, "utf8"), data);
  const xml = renderTextTemplate(template, data);
  ensureDir(outputPath);
  fs.writeFileSync(outputPath, xml, "utf8");
  return unresolvedInText(xml);
}

function templateIfExists(runDir, relPath) {
  const fullPath = path.join(runDir, relPath);
  return fs.existsSync(fullPath) ? fullPath : null;
}

function shouldRender(key, documentSet) {
  return documentSet.size === 0 || documentSet.has(key);
}

function normalizedApprovalStatus(data) {
  return String(data?.approval?.status ?? "").trim().toLowerCase();
}

function buildRenderData(data) {
  const templateFields =
    data?.template_fields && typeof data.template_fields === "object" && !Array.isArray(data.template_fields)
      ? data.template_fields
      : {};
  return { ...data, ...templateFields };
}

function main() {
  const args = parseArgs(process.argv);
  const runDir = path.resolve(args["run-dir"] || ".");
  const referencePath = path.resolve(args.reference || path.join(runDir, STANDARD.reference));
  const data = readJson(referencePath);
  if (args["require-approval"] && normalizedApprovalStatus(data) !== "approved") {
    throw new Error("Final generation requires approval.status to be approved.");
  }
  const renderData = buildRenderData(data);
  const rawDocumentSet = data?.meta?.document_set;
  const documentSet = new Set(Array.isArray(rawDocumentSet) ? rawDocumentSet : []);
  const outputs = [];
  const unresolved = {};
  const templates = [];

  for (const item of DOCX_OUTPUTS) {
    if (!shouldRender(item.key, documentSet)) continue;
    const template = templateIfExists(runDir, item.template);
    if (!template) continue;
    const out = path.join(runDir, item.output);
    unresolved[item.output] = renderDocx(template, out, renderData);
    outputs.push(item.output);
    templates.push(item.template);
  }

  const xmlTemplate = shouldRender(XML_OUTPUT.key, documentSet) ? templateIfExists(runDir, XML_OUTPUT.template) : null;
  if (xmlTemplate) {
    const out = path.join(runDir, XML_OUTPUT.output);
    unresolved[XML_OUTPUT.output] = renderXml(xmlTemplate, out, renderData);
    outputs.push(XML_OUTPUT.output);
    templates.push(XML_OUTPUT.template);
  }

  const reportPath = path.join(runDir, STANDARD.report);
  let priorReport = {};
  if (fs.existsSync(reportPath)) {
    try {
      priorReport = readJson(reportPath);
    } catch {
      priorReport = {};
    }
  }
  const report = {
    ...priorReport,
    run_dir: ".",
    run_id: path.basename(runDir),
    reference: relToRun(referencePath, runDir),
    templates,
    outputs,
    approval_status: normalizedApprovalStatus(data) || null,
    approval_required: Boolean(args["require-approval"]),
    unresolved_output_placeholders: unresolved,
    generated_at: new Date().toISOString()
  };
  ensureDir(reportPath);
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  console.log(JSON.stringify(report, null, 2));
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
