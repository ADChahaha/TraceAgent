import { ArrowUpRight, BookOpen, FileText, ListChecks, Plus } from "lucide-react";
import styles from "./workspace.module.css";

export function WorkspaceOverview({ count, onAdd, onPrompt }: {
  count: number; onAdd: () => void; onPrompt: (prompt: string) => void;
}) {
  return <div className={styles.overview}>
    <div className={styles.overviewIcon}><BookOpen size={36} strokeWidth={1.5} /></div>
    <h1>Your document workspace</h1>
    <p className={styles.meta}>{count} {count === 1 ? "source" : "sources"} · PDF & DOCX</p>
    <p className={styles.description}>Bring your documents together. Ask questions, explore the details, and follow every answer back to its source.</p>
    <div className={styles.quickActions}>
      <button type="button" onClick={onAdd}><span className={styles.actionIcon}><Plus size={25} /></span><span>Add sources<small>Upload your documents</small></span><ArrowUpRight size={17} /></button>
      <button type="button" onClick={() => onPrompt("Summarize the main ideas")}><span className={styles.actionIcon}><FileText size={24} /></span><span>Get a summary<small>Find the main ideas</small></span><ArrowUpRight size={17} /></button>
      <button type="button" onClick={() => onPrompt("What are the key findings?")}><span className={styles.actionIcon}><ListChecks size={24} /></span><span>Explore the details<small>Discover key findings</small></span><ArrowUpRight size={17} /></button>
    </div>
  </div>;
}
