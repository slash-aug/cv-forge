// jsdom has no DataTransfer and only accepts a real FileList for input.files.
// Minimal stand-ins so attachFile can run its production path in tests.
class FakeFileList extends Array<File> {
  item(i: number): File | null {
    return this[i] ?? null;
  }
}

class FakeDataTransfer {
  private list = new FakeFileList();
  items = { add: (file: File): void => void this.list.push(file) };
  get files(): FileList {
    return this.list as unknown as FileList;
  }
}

const assigned = new WeakMap<HTMLInputElement, FileList>();
const native = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "files");

Object.defineProperty(globalThis, "DataTransfer", { value: FakeDataTransfer, configurable: true });
Object.defineProperty(HTMLInputElement.prototype, "files", {
  configurable: true,
  get(this: HTMLInputElement) {
    return assigned.get(this) ?? native?.get?.call(this) ?? null;
  },
  set(this: HTMLInputElement, value: FileList) {
    if (this.type === "file") assigned.set(this, value);
  },
});
