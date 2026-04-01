import { useState, useRef, useCallback, useEffect } from "react";
import { uploadB3, uploadInforme, getApuracao } from "./services/api";

// ─── HELPERS ──────────────────────────────────────────────────────────────────
const fmt = (n) =>
  typeof n === "number"
    ? n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })
    : n;

// ─── MARKDOWN RENDERER ────────────────────────────────────────────────────────
function MD({ text }) {
  const lines = text.split("\n");
  const elements = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("### ")) {
      elements.push(<h3 key={i} className="md-h3">{line.slice(4)}</h3>);
    } else if (line.startsWith("## ")) {
      elements.push(<h2 key={i} className="md-h2">{line.slice(3)}</h2>);
    } else if (line.startsWith("# ")) {
      elements.push(<h1 key={i} className="md-h1">{line.slice(2)}</h1>);
    } else if (line.startsWith("---")) {
      elements.push(<hr key={i} className="md-hr" />);
    } else if (line.startsWith("| ")) {
      // Table
      const tableLines = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        tableLines.push(lines[i]);
        i++;
      }
      const rows = tableLines
        .filter((l) => !l.match(/^\|[\s\-|]+\|$/))
        .map((l) => l.split("|").filter((_, ci) => ci > 0 && ci < l.split("|").length - 1).map((c) => c.trim()));
      elements.push(
        <div key={`t${i}`} className="md-table-wrap">
          <table className="md-table">
            <thead>
              <tr>{rows[0]?.map((c, ci) => <th key={ci}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.slice(1).map((row, ri) => (
                <tr key={ri}>{row.map((c, ci) => <td key={ci}>{inlineRender(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      const items = [];
      while (i < lines.length && (lines[i].startsWith("- ") || lines[i].startsWith("* "))) {
        items.push(lines[i].slice(2));
        i++;
      }
      elements.push(<ul key={`ul${i}`} className="md-ul">{items.map((it, ii) => <li key={ii}>{inlineRender(it)}</li>)}</ul>);
      continue;
    } else if (line.match(/^\d+\. /)) {
      const items = [];
      while (i < lines.length && lines[i].match(/^\d+\. /)) {
        items.push(lines[i].replace(/^\d+\. /, ""));
        i++;
      }
      elements.push(<ol key={`ol${i}`} className="md-ol">{items.map((it, ii) => <li key={ii}>{inlineRender(it)}</li>)}</ol>);
      continue;
    } else if (line === "") {
      elements.push(<div key={i} className="md-gap" />);
    } else {
      elements.push(<p key={i} className="md-p">{inlineRender(line)}</p>);
    }
    i++;
  }
  return <div className="md-root">{elements}</div>;
}

function inlineRender(text) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[INSERIR:[^\]]+\])/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`")) return <code key={i} className="md-code">{p.slice(1, -1)}</code>;
    if (p.startsWith("[INSERIR:")) return <span key={i} className="md-insert">{p}</span>;
    return p;
  });
}

// ─── FILE CHIP ────────────────────────────────────────────────────────────────
function FileChip({ file, onRemove }) {
  const icon = file.type === "application/pdf" ? "📄" : "📊";
  const kb = (file.size / 1024).toFixed(0);
  return (
    <div className="file-chip">
      <span>{icon}</span>
      <span className="file-chip-name">{file.name}</span>
      <span className="file-chip-size">{kb}kb</span>
      <button onClick={onRemove} className="file-chip-remove">×</button>
    </div>
  );
}

// ─── DROP ZONE ────────────────────────────────────────────────────────────────
function DropZone({ onFiles }) {
  const [over, setOver] = useState(false);
  const inputRef = useRef();

  const handle = (files) => {
    const valid = Array.from(files).filter(
      (f) => f.type === "application/pdf" || f.name.endsWith(".csv") || f.name.endsWith(".xlsx")
    );
    if (valid.length) onFiles(valid);
  };

  return (
    <div
      className={`drop-zone ${over ? "drop-over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); handle(e.dataTransfer.files); }}
      onClick={() => inputRef.current.click()}
    >
      <input ref={inputRef} type="file" multiple accept=".pdf,.csv,.xlsx" style={{ display: "none" }}
        onChange={(e) => handle(e.target.files)} />
      <div className="drop-icon">{over ? "⬇" : "⊕"}</div>
      <div className="drop-title">Arraste ou clique para importar</div>
      <div className="drop-sub">PDF · CSV · XLSX — Informe de rendimentos, notas de corretagem, extrato B3, extratos bancários</div>
    </div>
  );
}


// ─── MAIN APP ─────────────────────────────────────────────────────────────────
export default function IRApp() {
  const [tab, setTab] = useState("dados");
  const [files, setFiles] = useState([]);
  
  const [declaration, setDeclaration] = useState("");
  const [genLoading, setGenLoading] = useState(false);
  const [progressMsg, setProgressMsg] = useState("");

  const addFiles = useCallback((newFiles) => {
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      return [...prev, ...newFiles.filter((f) => !names.has(f.name))];
    });
  }, []);

  const processarArquivos = async () => {
    setProgressMsg("Enviando arquivos para o Cérebro local...");
    for (const f of files) {
      try {
        if (f.name.toLowerCase().endsWith(".csv")) {
          await uploadB3(f, 1);
        } else if (f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf")) {
          await uploadInforme(f, 1);
        }
      } catch (err) {
        console.error("Erro ao fazer upload do arquivo:", f.name, err);
      }
    }
    setProgressMsg("Upload finalizado. Operações salvas no banco.");
  };

  const generateDeclaration = async () => {
    setGenLoading(true);
    setTab("declaracao");
    
    try {
      // 1. Enviar arquivos primeiro
      await processarArquivos();

      setProgressMsg("Rodando Apuração Cronológica (On-the-fly)...");

      // 2. Extrair Apuração local
      const data = await getApuracao(1, 2024);

      // 3. Formatar o Markdown Matemático
      let md = `## RELATÓRIO DE APURAÇÃO IRPF 2025 — ANO-BASE 2024\n`;
      md += `### MARCOS (Contribuinte ID: ${data.contribuinte_id})\n\n---\n`;

      md += `### 📊 APURAÇÃO MENSAL B3 E COMPENSAÇÃO DE PREJUÍZOS\n`;
      md += `| Mês/Ano | Volume Vendas | Lucro Isento | Lucro Tributável | Prej. Compensado | Prej. Gerado | Imposto Devido (DARF) |\n`;
      md += `|---------|---------------|--------------|------------------|------------------|--------------|-----------------------|\n`;
      
      data.meses.forEach((m) => {
        md += `| ${String(m.mes).padStart(2, '0')}/${m.ano} | R$ ${m.total_vendas} | R$ ${m.lucro_isento} | R$ ${m.lucro_tributavel} | R$ ${m.prejuizo_acumulado_utilizado} | R$ ${m.prejuizo_mes_gerado} | **R$ ${m.imposto_devido}** |\n`;
      });
      
      md += `\n---\n`;
      md += `### 💵 FECHAMENTO ANUAL (TOTAIS)\n`;
      md += `| OBRIGAÇÃO | VALOR APURADO |\n`;
      md += `|-----------|---------------|\n`;
      md += `| **Lucro Isento (< 20k/mês)** | R$ ${data.total_lucro_isento_ano} |\n`;
      md += `| **Lucro Tributável** | R$ ${data.total_lucro_tributavel_ano} |\n`;
      md += `| **Impostos a Pagar / Pagos** | R$ ${data.total_imposto_devido_ano} |\n`;
      md += `| **Crédito de Prejuízo (próx. ano)** | R$ ${data.saldo_prejuizo_a_compensar_final_ano} |\n`;

      if (data.alertas_cripto && data.alertas_cripto.length > 0) {
        md += `\n---\n### 🚨 AUDITORIA REGULATÓRIA - CRIPTOATIVOS\n`;
        data.alertas_cripto.forEach(al => {
           md += `- **Mês ${al.mes}/${al.ano}**: ${al.mensagem} (Vendas: R$ ${al.total_vendas} | Teto Isenção: R$ ${al.limite_isencao})\n`;
        });
      } else {
        md += `\n---\n### ✅ AUDITORIA REGULATÓRIA - CRIPTOATIVOS\n- Nenhuma violação ao limite de R$ 35.000,00 detectada no ano base de 2024.\n`;
      }

      setDeclaration(md);
    } catch (err) {
      console.error(err);
      setDeclaration(`Erro de conexão com o Back-End Local.\n\nDetalhes do Erro: ${err.message}\nCertifique-se de que o Uvicorn (FastAPI) está rodando.`);
    } finally {
      setGenLoading(false);
      setProgressMsg("");
    }
  };


  const TABS = [
    { id: "dados", label: "① Dados", sub: "Importar & Processar" },
    { id: "declaracao", label: "② Apuração e Impostos", sub: "Relatório Anual Local" },
  ];

  return (
    <div className="app">
      <style>{CSS}</style>

      {/* HEADER */}
      <header className="header">
        <div className="header-brand">
          <div className="brand-icon">IR</div>
          <div>
            <div className="brand-title">IRPF 2025 — Motor Local Deterministico</div>
            <div className="brand-sub">ANO-BASE 2024 · APURAÇÃO DE B3 E CRIPTO</div>
          </div>
        </div>
        <div className="header-badges">
          <span className="badge badge-green">● Localhost:8000</span>
          <span className="badge badge-gold">Marcos · 23 anos</span>
        </div>
      </header>

      {/* TABS */}
      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab ${tab === t.id ? "tab-active" : ""}`} onClick={() => setTab(t.id)}>
            <span className="tab-label">{t.label}</span>
            <span className="tab-sub">{t.sub}</span>
          </button>
        ))}
      </nav>

      {/* CONTENT */}
      <main className="main">
        {/* ── DADOS ── */}
        {tab === "dados" && (
          <div className="dados-layout">
            <div className="panel">
              <div className="panel-title">📁 Importar Documentos</div>
              <div className="panel-hint">
                Os arquivos serão enviados de forma segura ao seu banco de dados local SQLite rodando na porta 8000.
              </div>
              <DropZone onFiles={addFiles} />
              {files.length > 0 && (
                <div className="files-list">
                  {files.map((f, i) => (
                    <FileChip key={i} file={f} onRemove={() => setFiles((p) => p.filter((_, j) => j !== i))} />
                  ))}
                </div>
              )}
            </div>

            <div className="dados-actions">
              <button 
                className="btn btn-primary" 
                onClick={generateDeclaration}
                disabled={genLoading}
                style={{ width: "100%", padding: "16px", fontSize: "14px" }}
              >
                {genLoading ? "Apurando Tributos..." : "⚡ Processar Arquivos e Extrair Apuração Anual"}
              </button>
            </div>
          </div>
        )}

        {/* ── DECLARAÇÃO LOCAl ── */}
        {tab === "declaracao" && (
          <div className="gen-layout">
            {!declaration && !genLoading && (
              <div className="gen-empty">
                <div className="gen-empty-icon">📊</div>
                <p>Nenhuma apuração rodada ainda. Vá para Dados para importar seus arquivos e rodar o Motor.</p>
                <button className="btn btn-primary" onClick={() => setTab("dados")}>Voltar aos Arquivos</button>
              </div>
            )}
            
            {genLoading && tab === "declaracao" && (
              <div className="gen-loading">
                <div className="spinner" />
                <p>{progressMsg || "Aplicando regras na base de dados..."}</p>
              </div>
            )}
            
            {declaration && !genLoading && (
              <div className="gen-content">
                <div className="gen-toolbar">
                  <span className="gen-label">📊 Relatório Consolidado de Apuração</span>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn btn-secondary btn-sm" onClick={() => {
                      navigator.clipboard.writeText(declaration);
                    }}>⎘ Copiar Markup</button>
                  </div>
                </div>
                <div className="gen-notice">
                  ℹ️ Apuração calculada deterministicamente baseada nos arquivos ingeridos pelo motor do Agent IR.
                </div>
                <div className="gen-body"><MD text={declaration} /></div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

// ─── CSS ──────────────────────────────────────────────────────────────────────
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  .app {
    min-height: 100vh;
    background: #070a0d;
    color: #c8c4bc;
    font-family: 'IBM Plex Mono', monospace;
    display: flex;
    flex-direction: column;
  }

  /* HEADER */
  .header {
    background: #0b0e13;
    border-bottom: 1px solid #1a2030;
    padding: 12px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 10px;
  }
  .header-brand { display: flex; align-items: center; gap: 12px; }
  .brand-icon {
    width: 38px; height: 38px;
    background: linear-gradient(135deg, #b8872a, #5a3e10);
    border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 13px; color: #f0d080;
    letter-spacing: -1px;
    box-shadow: 0 0 16px #b8872a30;
  }
  .brand-title { font-size: 13px; font-weight: 600; color: #d4c070; letter-spacing: 0.02em; }
  .brand-sub { font-size: 9px; color: #404550; letter-spacing: 0.1em; margin-top: 2px; }
  .header-badges { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .badge { font-size: 10px; padding: 3px 10px; border-radius: 20px; letter-spacing: 0.06em; }
  .badge-green { background: #0d1f14; border: 1px solid #1e4028; color: #4a9060; }
  .badge-gold { background: #1a1408; border: 1px solid #3a2808; color: #b8872a; }

  /* TABS */
  .tabs {
    display: flex;
    background: #090c11;
    border-bottom: 1px solid #14202e;
    overflow-x: auto;
  }
  .tab {
    flex: 1; min-width: 100px;
    padding: 10px 16px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #404860;
    cursor: pointer;
    font-family: inherit;
    font-size: 10px;
    text-align: left;
    transition: all 0.15s;
  }
  .tab:hover { color: #8090b0; background: #0d1018; }
  .tab-active { color: #d4c070 !important; border-bottom-color: #b8872a !important; background: #0d1018 !important; }
  .tab-label { display: block; font-weight: 600; font-size: 11px; letter-spacing: 0.04em; }
  .tab-sub { display: block; font-size: 9px; color: inherit; opacity: 0.7; margin-top: 2px; letter-spacing: 0.04em; }

  /* MAIN */
  .main { flex: 1; overflow: hidden; display: flex; flex-direction: column; }

  /* DADOS */
  .dados-layout {
    flex: 1; overflow-y: auto; padding: 20px;
    display: flex; flex-direction: column; gap: 20px;
    max-width: 900px; width: 100%; margin: 0 auto;
  }
  .panel {
    background: #0b0f14;
    border: 1px solid #18222e;
    border-radius: 10px;
    padding: 18px 20px;
  }
  .panel-title { font-size: 12px; font-weight: 600; color: #d4c070; letter-spacing: 0.06em; margin-bottom: 6px; }
  .panel-hint { font-size: 11px; color: #404860; line-height: 1.5; margin-bottom: 14px; }

  .drop-zone {
    border: 1px dashed #243040;
    border-radius: 8px;
    padding: 28px 20px;
    text-align: center;
    cursor: pointer;
    transition: all 0.15s;
  }
  .drop-zone:hover, .drop-over { border-color: #b8872a60; background: #1a120440; }
  .drop-icon { font-size: 24px; margin-bottom: 8px; color: #b8872a; }
  .drop-title { font-size: 12px; color: #8090a0; font-weight: 600; margin-bottom: 4px; }
  .drop-sub { font-size: 10px; color: #404860; line-height: 1.5; }

  .files-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .file-chip {
    display: flex; align-items: center; gap: 6px;
    background: #101820; border: 1px solid #1e3040;
    border-radius: 20px; padding: 4px 10px;
    font-size: 10px; color: #809ab0;
  }
  .file-chip-name { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #a0b8c8; }
  .file-chip-size { color: #404860; }
  .file-chip-remove { background: none; border: none; color: #604040; cursor: pointer; font-size: 14px; padding: 0; line-height: 1; }
  .file-chip-remove:hover { color: #c06060; }

  .dados-actions {
    display: flex; gap: 10px; flex-wrap: wrap;
    padding: 4px 0 8px;
  }

  /* BUTTONS */
  .btn {
    font-family: inherit;
    font-size: 11px;
    font-weight: 600;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    cursor: pointer;
    letter-spacing: 0.04em;
    transition: all 0.15s;
  }
  .btn-primary {
    background: linear-gradient(135deg, #b8872a, #6a4a10);
    color: #f0d080;
    box-shadow: 0 0 16px #b8872a20;
  }
  .btn-primary:hover:not(:disabled) { box-shadow: 0 0 24px #b8872a40; filter: brightness(1.1); }
  .btn-secondary {
    background: #10181f;
    border: 1px solid #1e2e3e;
    color: #6090a0;
  }
  .btn-secondary:hover { border-color: #304050; color: #80b0c8; }
  .btn-sm { font-size: 10px; padding: 6px 12px; }
  .btn:disabled { opacity: 0.5; cursor: wait; }

  /* GEN */
  .gen-layout {
    flex: 1; display: flex; flex-direction: column; overflow: hidden;
  }
  .gen-empty {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    text-align: center; padding: 40px 20px; gap: 14px;
  }
  .gen-empty-icon { font-size: 40px; }
  .gen-empty p { font-size: 12px; color: #506070; max-width: 360px; line-height: 1.6; }
  .gen-loading {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 16px;
  }
  .gen-loading p { font-size: 11px; color: #506070; }
  .spinner {
    width: 32px; height: 32px;
    border: 2px solid #1a2030;
    border-top-color: #b8872a;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .gen-content {
    flex: 1; display: flex; flex-direction: column; overflow: hidden;
  }
  .gen-toolbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 20px;
    border-bottom: 1px solid #14202e;
    background: #090c11;
  }
  .gen-label { font-size: 11px; color: #d4c070; font-weight: 600; letter-spacing: 0.04em; }
  .gen-notice {
    font-size: 10px; color: #506070; background: #1a1208;
    border-bottom: 1px solid #14202e;
    padding: 8px 20px; line-height: 1.5;
  }
  .gen-body {
    flex: 1; overflow-y: auto; padding: 20px;
    max-width: 900px; width: 100%; margin: 0 auto;
  }

  /* MARKDOWN */
  .md-root { font-family: 'IBM Plex Mono', monospace; }
  .md-h1 { font-family: 'Libre Baskerville', serif; font-size: 18px; color: #d4c070; margin: 20px 0 10px; font-style: italic; }
  .md-h2 { font-size: 14px; color: #b8a060; margin: 16px 0 8px; letter-spacing: 0.04em; font-weight: 700; border-bottom: 1px solid #1e2830; padding-bottom: 6px; }
  .md-h3 { font-size: 11px; color: #8090b0; margin: 12px 0 6px; letter-spacing: 0.08em; text-transform: uppercase; }
  .md-hr { border: none; border-top: 1px solid #1e2830; margin: 12px 0; }
  .md-p { font-size: 12px; color: #a0b0c0; line-height: 1.7; margin: 5px 0; }
  .md-ul, .md-ol { padding-left: 18px; margin: 6px 0; }
  .md-ul li, .md-ol li { font-size: 12px; color: #a0b0c0; line-height: 1.7; margin: 3px 0; }
  .md-ul { list-style: disc; }
  .md-ol { list-style: decimal; }
  .md-gap { height: 6px; }
  .md-code { background: #101820; border: 1px solid #18283a; border-radius: 4px; padding: 1px 5px; font-size: 11px; color: #70c090; }
  .md-insert { background: #1a0e08; border: 1px solid #3a1e08; border-radius: 4px; padding: 1px 5px; color: #d08040; font-size: 11px; }
  .md-root strong { color: #c8b060; }

  .md-table-wrap { overflow-x: auto; margin: 10px 0; }
  .md-table { border-collapse: collapse; width: 100%; font-size: 11px; }
  .md-table th {
    background: #0f1820; color: #6090a0;
    padding: 7px 12px; text-align: left;
    border: 1px solid #18283a;
    font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
  }
  .md-table td {
    padding: 6px 12px; border: 1px solid #12202e;
    color: #90a8b8; background: #080c10;
    line-height: 1.5;
  }
  .md-table tr:nth-child(even) td { background: #0a0e14; }

  /* SCROLLBAR */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #1a2838; border-radius: 4px; }
`;
