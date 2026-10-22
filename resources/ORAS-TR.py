import json
import os
import random
import re
import time

import torch
from huggingface_hub import scan_cache_dir
from safetensors import safe_open
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


MODEL_NAME = os.environ.get("TRANSLATION_MODEL", "facebook/nllb-200-distilled-600M")
BATCH_SIZE = max(1, int(os.environ.get("TRANSLATION_BATCH_SIZE", "32")))
BACKEND = os.environ.get("TRANSLATION_BACKEND", "auto").casefold()
LANGUAGE_TOKENS = {
    # European
    "de": "deu_Latn",   # German
    "it": "ita_Latn",   # Italian
    "pt": "por_Latn",   # Portuguese
    "nl": "nld_Latn",   # Dutch
    "da": "dan_Latn",   # Danish
    "fi": "fin_Latn",   # Finnish
    "pl": "pol_Latn",   # Polish
    "cs": "ces_Latn",   # Czech
    "uk": "ukr_Cyrl",   # Ukrainian
    "ru": "rus_Cyrl",   # Russian
    "tr": "tur_Latn",   # Turkish
    "el": "ell_Grek",   # Greek
    "en": "eng_Latn",   # English 
    "es": "spa_Latn",   # Spanish
    "nb": "nob_Latn",   # Norwegian Bokmål
    "sv": "swe_Latn",   # Swedish
    "fr": "fra_Latn",   # French

    # Asian
    "ko": "kor_Hang",   # Korean
    "zh": "zho_Hans",   # Simplified Chinese
    "hi": "hin_Deva",   # Hindi
    "id": "ind_Latn",   # Indonesian
    "vi": "vie_Latn",   # Vietnamese
    "th": "tha_Thai",   # Thai
    "ja": "jpn_Jpan",   # Japanese

    # Middle Eastern / South Asian
    "ar": "arb_Arab",   # Arabic
    "he": "heb_Hebr",   # Hebrew
    "fa": "pes_Arab",   # Persian
    "ur": "urd_Arab",   # Urdu
}

#Prevents the translation of any control codes, including the gender symbols (which most of the time called female 'staff' lol.)
CONTROL_CODE_PATTERN = re.compile(r"(\[.*?\]|\\[a-zA-Z]|[♂♀])")

# Section limits for specific text sections due to constraints in ORAS' code.
# Section limit descriptions can be found in the 'docs/charlimits.md' file.
 

SECTION_LIMITS = {
    5: 20, 14: 16, 15: 16, 18: 12, 90: 16, 98: 12,
    0: 16, 21: 16, 37: 16, 113: 16, 114: 16, 115: 16, 116: 16,
    153: 16, 154: 16, 22: 16, 51: 12,
}


def restore_shared_embedding(model):
    cache_files = []
    for repository in scan_cache_dir().repos:
        if repository.repo_id != MODEL_NAME:
            continue
        for revision in repository.revisions:
            candidate = revision.snapshot_path / "model.safetensors"
            if candidate.is_file():
                cache_files.append(candidate)
    if not cache_files:
        raise FileNotFoundError(
            f"No safetensors checkpoint found in the Hugging Face cache for {MODEL_NAME}."
        )

    checkpoint_path = max(cache_files, key=lambda path: path.stat().st_mtime)
    with safe_open(str(checkpoint_path), framework="pt", device="cpu") as checkpoint:
        shared_weight = checkpoint.get_tensor("lm_head.weight")
    model.model.shared.weight = torch.nn.Parameter(shared_weight)
    model.tie_weights()


def detect_backend():
    if torch.cuda.is_available():
        return "rocm" if torch.version.hip else "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    if os.name == "nt":
        try:
            import torch_directml
        except ImportError:
            pass
        else:
            return "directml"
    return "cpu"


def select_device():
    global BACKEND
    if BACKEND == "auto":
        BACKEND = detect_backend()
    if BACKEND == "cpu":
        return torch.device("cpu") # Uses CPU
    if BACKEND == "mps":
        if not torch.backends.mps.is_available():
            raise RuntimeError(
                "MPS was requested but no compatible Apple Silicon device is available."
            )
        return torch.device("mps")
    if BACKEND in {"cuda", "rocm"}:
        if not torch.cuda.is_available():
            backend_name = "ROCm" if BACKEND == "rocm" else "CUDA" # Attempt to load either CUDA or ROCm if available
            raise RuntimeError(
                f"{backend_name} was requested but no compatible device is available."
            )
        if BACKEND == "rocm" and torch.version.hip is None:
            raise RuntimeError(
                "ROCm was requested, but this PyTorch installation has no ROCm support."
            )
        return torch.device("cuda")
    if BACKEND == "directml":
        try:
            import torch_directml
        except ImportError as error:
            raise RuntimeError(
                "DirectML was requested but torch-directml is not installed. "
                "Run: python -m pip install torch-directml"
            ) from error
        return torch_directml.device()
    raise ValueError(
        f"Unsupported TRANSLATION_BACKEND={BACKEND!r}; "
        "use mps, directml, rocm, cuda, or cpu."
    )


DEVICE = select_device()
DEVICE_NAME = str(DEVICE)


def prompt_for_folder(prompt, example_path, create=False):
    entered_path = input(f"{prompt} (example: {example_path}): ").strip().strip('"')
    if not entered_path:
        raise ValueError(f"A folder path is required for {prompt.lower()}")
    folder_path = os.path.abspath(os.path.expanduser(entered_path))
    if create:
        os.makedirs(folder_path, exist_ok=True)
    elif not os.path.isdir(folder_path):
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    return folder_path


def format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def split_source(filepath):
    structure = []
    texts = []
    current_text_file = -1
    skip_files = {94}
    
    with open(filepath, "r", encoding="utf-16") as file:
        lines = file.readlines()

    for line in lines:
        text = line.rstrip("\n")
        if not text:
            structure.append({"type": "newline"})
            continue
        if "Text File" in text:
            try:
                current_text_file = int(text.split(":")[1].strip())
            except (IndexError, ValueError):
                pass
            structure.extend(({"type": "code", "content": text}, {"type": "newline"}))
            continue

        for part in CONTROL_CODE_PATTERN.split(text):
            is_code = (
                CONTROL_CODE_PATTERN.match(part)
                or not part.strip()
                or set(part.strip()).issubset({"-", "~", "=", "*", "_", ":", ".", ",", "!", "?", "'", '"', "(", ")", "[", "]", "{", "}", "<", ">", "/", "\\", "|", "@", "#", "$", "%", "^", "&", "+", "`"})
            ) # Ignores lines that are only punctuation or whitespace, as well as control codes
            if is_code or current_text_file in skip_files:
                structure.append({"type": "code", "content": part})
            else:
                structure.append({"type": "text", "file_id": current_text_file})
                texts.append(part)
        structure.append({"type": "newline"})
    return structure, texts


def rebuild_lines(structure, translated_text): # Rebuilds the original lines from the structure and translated text, ensuring that control codes and punctuation are preserved.
    rebuilt_lines = []
    current_line = ""
    text_index = 0
    for item in structure:
        if item["type"] == "newline":
            rebuilt_lines.append(current_line + "\n")
            current_line = ""
        elif item["type"] == "code":
            current_line += item["content"]
        else:
            translated = translated_text[text_index]
            max_length = SECTION_LIMITS.get(item["file_id"])
            if max_length is not None:
                translated = translated[:max_length]
            current_line += translated
            text_index += 1
    return rebuilt_lines


class HardwareTranslator:
    def __init__(self):
        print(f"Loading {MODEL_NAME} on {DEVICE_NAME}...") # States the model name and the device being used for translation
        if BACKEND in {"cuda", "rocm"}:
            print(f"{BACKEND.upper()} device: {torch.cuda.get_device_name(0)}")
        dtype = torch.float16 if BACKEND in {"cuda", "rocm"} else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            MODEL_NAME, dtype=dtype, use_safetensors=True,
            low_cpu_mem_usage=False,
        )
        restore_shared_embedding(self.model)
        self.model = self.model.to(DEVICE)
        self.model.generation_config.max_length = None
        self.model.eval()

    def translate(self, texts, source_code, target_code):
        self.tokenizer.src_lang = LANGUAGE_TOKENS[source_code]
        target_token = self.tokenizer.convert_tokens_to_ids(LANGUAGE_TOKENS[target_code])
        translated = []
        started_at = time.perf_counter()
        total = len(texts)
        batch_durations = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch_started_at = time.perf_counter()
            batch = texts[start:start + BATCH_SIZE]
            encoded = self.tokenizer(
                batch, return_tensors="pt", padding=True, truncation=True,
                max_length=512,
            ).to(DEVICE)
            with torch.inference_mode():
                generated = self.model.generate(
                    **encoded, forced_bos_token_id=target_token,
                    max_new_tokens=256,
                )
            translated.extend(self.tokenizer.batch_decode(generated, skip_special_tokens=True))
            completed = start + len(batch)
            elapsed = time.perf_counter() - started_at
            batch_durations.append(time.perf_counter() - batch_started_at)
            recent_durations = batch_durations[-10:]
            average_batch_duration = sum(recent_durations) / len(recent_durations)
            remaining_batches = (total - completed + BATCH_SIZE - 1) // BATCH_SIZE
            eta = remaining_batches * average_batch_duration
            print(
                f"    {source_code}->{target_code}: {completed}/{total} " 
                f"({completed / total:.1%}); elapsed: {format_duration(elapsed)}; " # Percentage of completion and elapsed time
                f"ETA: {format_duration(eta)}", # ETA for current 'hop' (translation batch)
                flush=True,
            )
        final_results = []
        for result, original in zip(translated, texts):
            # Strip musical notes and any backslash NOT followed by a letter
            cleaned = re.sub(r'\\(?![a-zA-Z])', '', result.replace("♪", ""))
            
            # Fall back to original English ONLY if the string is empty or just punctuation
            if not cleaned.strip() or set(cleaned.strip()).issubset({')', '(', '.', ' '}):
                final_results.append(original)
            else:
                # Dynamic Cap: 150 chars OR twice the length of the original English text (whichever is larger)
                safe_limit = max(150, len(original) * 2)
                
                if len(cleaned) > safe_limit:
                    cleaned = cleaned[:safe_limit]
                    
                final_results.append(cleaned)
                
        return final_results


def main():
    example_root = (
        "/Users/eviolites/Desktop"
        if BACKEND == "mps"
        else "D:/GitHub/ORAS-TR"
    )
    directory = prompt_for_folder(
        "Import folder", os.path.join(example_root, "translation-input")
    )
    export_directory = prompt_for_folder(
        "Export folder",
        os.path.join(example_root, "translation-output"),
        create=True,
    )
    state_path = os.path.join(export_directory, "translated.state.json")
    log_path = os.path.join(export_directory, "translation.log")

    state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    if state.get("source_directory") != directory:
        state = {}

    available_languages = [code for code in LANGUAGE_TOKENS if code != "en"]
    saved_languages = state.get("languages")
    if (isinstance(saved_languages, list) and len(saved_languages) >= 2
            and saved_languages[0] == "en" and saved_languages[-1] == "en"
            and all(language in LANGUAGE_TOKENS for language in saved_languages)):
        languages = saved_languages
    else:
        maximum_intermediate = len(available_languages)
        while True:
            language_count = input(
                f"How many intermediate languages?  "
                "NOTE: Anything over 4 will take a long time to translate, and may result in a lot of gibberish. "
                "Proceed with caution."
                "(0-{maximum_intermediate}, default 4): "
            ).strip()
            if not language_count:
                intermediate_count = 4
                break
            try:
                intermediate_count = int(language_count)
            except ValueError:
                print("Please enter a whole number.")
                continue
            if 0 <= intermediate_count <= maximum_intermediate:
                break
            print(f"Please enter a number from 0 to {maximum_intermediate}.")
        languages = [
            "en", *random.sample(available_languages, intermediate_count), "en"
        ]
    print(f"Translation sequence: {' -> '.join(languages)}") # Final sequence of languages to be used for translation, starting and ending with English

    output_names = {"translated.txt"}
    source_files = []
    source_output_names = {}
    text_files = []
    for filename in sorted(os.listdir(directory)):
        filename_key = filename.casefold()
        if not filename_key.endswith(".txt") or filename_key in output_names:
            continue
        text_files.append(filename)
        candidate_path = os.path.join(directory, filename)
        with open(candidate_path, "r", encoding="utf-16") as candidate_file:
            candidate_lines = candidate_file.readlines()
        if len(candidate_lines) >= 4 and "somewhere" in candidate_lines[3].casefold(): # Uses the 4th line to identify the file as gametext.txt, which contains in-game text, while storytext.txt is identified by the presence of "clunk!" in the 26th line.
            source_files.append(filename)
            source_output_names[filename] = "gametext.txt" 
        elif len(candidate_lines) >= 26 and "clunk!" in candidate_lines[25].casefold(): # Were there probably better identifiers available? Yes. Did I use them? No. Why? Because I was lazy, lol
            source_files.append(filename)
            source_output_names[filename] = "storytext.txt"
    if not source_files:
        if text_files:
            response = input(
                "No recognized source markers were found. These files may already "
                "have been translated. Proceed anyway? (Y/N): "
            ).strip().casefold()
            if response != "y":
                print("Translation cancelled.")
                return
            for filename in text_files:
                source_files.append(filename)
                source_output_names[filename] = filename
        else:
            raise FileNotFoundError(f"No .txt files found in {directory}")
    print(f"Found {len(source_files)} source files: {', '.join(source_files)}")
    source_index = state.get("source_index", 0)
    hop_start = state.get("hop_index", 0)
    if source_index >= len(source_files):
        print("All source files have already been translated.")
        return

    translator = HardwareTranslator()
    run_started_at = time.perf_counter()
    for current_source_index in range(source_index, len(source_files)):
        filename = source_files[current_source_index]
        filepath = os.path.join(directory, filename)
        output_name = source_output_names[filename]
        checkpoint_path = os.path.join(export_directory, output_name)
        current_hop_start = hop_start if current_source_index == source_index else 0
        input_path = checkpoint_path if current_hop_start and os.path.exists(checkpoint_path) else filepath
        structure, current_text = split_source(input_path)
        print(f"Processing {filename} ({len(current_text)} strings) on {DEVICE_NAME}...")

        for hop_index in range(current_hop_start, len(languages) - 1):
            started_at = time.perf_counter()
            source_code, target_code = languages[hop_index:hop_index + 2]
            positions = {}
            for index, text in enumerate(current_text):
                positions.setdefault(text, []).append(index)
            unique_texts = list(positions)
            unique_results = translator.translate(unique_texts, source_code, target_code)
            translated_by_text = dict(zip(unique_texts, unique_results))
            current_text = [
                translated_by_text[text] for text in current_text
            ]
            final_lines = rebuild_lines(structure, current_text)
            with open(checkpoint_path, "w", encoding="utf-16") as checkpoint_file:
                checkpoint_file.writelines(final_lines)
            with open(state_path, "w", encoding="utf-8") as state_file:
                json.dump({"source_directory": directory, "languages": languages,
                           "source_index": current_source_index,
                           "hop_index": hop_index + 1}, state_file)
            hop_duration = format_duration(time.perf_counter() - started_at)
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(
                    f"Saved {checkpoint_path} after {source_code}->{target_code} for "
                    f"{filename}; elapsed: {hop_duration}\n"
                )
            print(f"  {source_code}->{target_code}: {len(unique_texts)} unique strings in "
                  f"{hop_duration}")

        output_filepath = os.path.join(export_directory, output_name)
        with open(output_filepath, "w", encoding="utf-16") as output_file:
            output_file.writelines(rebuild_lines(structure, current_text))
        with open(state_path, "w", encoding="utf-8") as state_file:
            json.dump({"source_directory": directory, "languages": languages,
                       "source_index": current_source_index + 1, "hop_index": 0}, state_file)
        print(f"Successfully saved: {output_filepath}")

    total_duration = format_duration(time.perf_counter() - run_started_at)
    print(f"Completed translation run in {total_duration}")
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"Completed translation run; total elapsed: {total_duration}\n")


if __name__ == "__main__":
    main()