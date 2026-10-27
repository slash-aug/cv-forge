// Port of cvforge.answers.bank.normalise_question. Keep the stopword list identical.
const STOPWORDS = new Set([
  "a", "an", "the", "of", "to", "in", "on", "at", "for", "and", "or", "is", "are", "was", "were",
  "be", "do", "does", "did", "you", "your", "we", "our", "i", "me", "my", "it", "this", "that",
  "with", "as", "by", "from", "have", "has", "can", "will", "would", "o", "os", "as", "um", "uma",
  "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "por", "para", "e", "ou", "que",
  "com", "voce", "voces", "tem", "ter", "seu", "sua", "sao", "ser",
]);

const NON_WORD = /[^\p{L}\p{N}]+/u;
const COMBINING = /\p{M}/gu;

export function normaliseQuestion(text: string): string {
  // casefold turns the sharp s into "ss"; toLocaleLowerCase does not.
  const folded = text.normalize("NFKC").toLocaleLowerCase("und").replaceAll("ß", "ss");
  const plain = folded.normalize("NFKD").replace(COMBINING, "");
  return plain
    .split(NON_WORD)
    .filter((w) => w !== "" && !STOPWORDS.has(w))
    .join(" ");
}
