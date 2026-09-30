#!/usr/bin/env python3
"""
Train multi-class router classifier (v2) — more data, LogisticRegression.
"""
import json, os, sys, pickle, re, urllib.request, random, itertools

OUTPUT_DIR   = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH   = os.path.join(OUTPUT_DIR, "router-classifier.pkl")

TIERS = ["local", "flash", "pro", "vision", "video", "voice", "premium", "meta"]
TIER_SET = set(TIERS)

OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embeddings"
OLLAMA_MODEL     = "qwen3-embedding:0.6b"

# ── Template-based data generator ────────────────────────────────────
TEMPLATES = {
    "local": [
        "what is {thing}", "define {concept}", "how to {simple_task} in {lang}",
        "explain {concept} simply", "list {things}", "convert {a} to {b}",
        "what does {code_snippet} do", "install {tool} on {os}",
        "what is the {attribute} of {thing}", "tell me a {joke_type} joke",
        "review this code: {code_snippet}", "hello world in {lang}",
        "what time is it in {place}", "is {number} prime",
        "capital of {country}", "ping {host}",
        "sum of {n} and {m}", "how to comment in {lang}",
        "{greeting}", "what is the weather in {city}",
    ],
    "flash": [
        "write a {framework} {app_type} for {purpose}",
        "create a {tech} component for {feature}",
        "fix this bug: {bug_desc}",
        "add {feature} to this {app_type}",
        "write unit tests for {component}",
        "create a dockerfile for {app_type}",
        "build a cli tool that {purpose}",
        "deploy {app} to {platform}",
        "set up {ci_tool} for {project_type}",
        "create a sql query to {query_purpose}",
        "write a bash script to {automation_task}",
        "add error handling to {component}",
        "create a {platform} bot with {lang}",
        "build a rest api for {purpose}",
        "add logging to {component}",
        "refactor {component} to be async",
        "write a makefile for {project_type}",
        "create a migration script for {db}",
        "add input validation to {component}",
        "set up {linter} for {project_type}",
        "write middleware for {framework}",
        "create a {pattern} for {use_case}",
    ],
    "pro": [
        "design a {distributed_system} for {scale} users",
        "implement {algorithm} from scratch in {lang}",
        "{strategy} for {db} migration",
        "architecture for {scale} concurrent {system_type}",
        "implement a concurrent {data_structure} with {feature}",
        "design a plugin system with {advanced_feature}",
        "build a custom {complex_component}",
        "implement {distributed_concept} for {system_type}",
        "design a {pattern} for {complex_scenario}",
        "implement {algorithm} with {variant}",
        "build a custom {network_component}",
        "write a concurrent {app_type} with {advanced_feature}",
        "implement {data_structure} for collaborative editing",
        "design a real-time {system_type} pipeline",
        "build a custom {low_level_component} in {systems_lang}",
        "implement a distributed {primitive} with {tool}",
        "design a multi-tenant {app_type} schema",
        "build a custom {parser_type}",
        "implement rate limiting with {algorithm}",
        "design a {infra_component} architecture",
    ],
    "vision": [
        "what is in this {visual_input}",
        "describe this {visual_input}",
        "extract text from this {visual_input} ocr",
        "analyze this {chart_type} and explain the trend",
        "is this {object_type} showing defects",
        "read the text in this {document_type}",
        "what {objects} can you see in this picture",
        "analyze this {diagram_type} and explain the flow",
        "check if this image contains a {object_type}",
        "transcribe text from this {document_type}",
        "analyze this {design_type} and give feedback",
        "what is the {subject} in this photo",
        "read the barcode in this image",
        "compare these two {visual_input}s",
        "describe the scene in this {visual_input}",
        "extract data from this {infographic_type}",
        "analyze the color palette of this {design_type}",
        "find {feature} in this image",
        "read handwriting from this {document_type}",
        "check if this {visual_input} contains text",
    ],
    "video": [
        "generate a video from this {content_script}",
        "create a {duration} ad video for {product_type}",
        "turn this {content_type} into a video",
        "generate a talking head video from {source}",
        "create an animation from these {elements}",
        "make a video summary of this {content_type}",
        "generate a promo video for {platform}",
        "create a tutorial video about {topic}",
        "turn these slides into a video presentation",
        "generate background footage for {theme}",
        "make a video from this storyboard",
        "create a looping animation for {platform}",
        "generate an explainer video for {concept}",
        "add subtitles to this video",
        "create a before after comparison video",
        "generate a product demo video for {product_type}",
        "make a compilation video from {source} clips",
        "create a {platform} intro animation",
        "generate a video with {voice_style} voiceover",
        "turn this data into an animated {chart_type} video",
    ],
    "voice": [
        "convert this text to speech in {language}",
        "generate a voiceover for this {content_type}",
        "create a podcast from this {content_type}",
        "clone this voice from a {audio_sample}",
        "add narration to this {media_type}",
        "generate speech in {language} with {accent} accent",
        "create an audiobook from this {content_type}",
        "make a voice assistant reply for {use_case}",
        "generate a {style} voice impression",
        "create voice prompts for {system_type}",
        "convert this dialogue to speech with {speaker_count} speakers",
        "generate multiple character voices for {project}",
        "add voice dubbing to this video in {language}",
        "create a text to speech for my {platform} app",
        "generate a singing voice from {lyrics_source}",
        "make a voice announcement for {event_type}",
        "convert this {document_type} to audio",
        "create a voice tutorial for {topic}",
        "generate speech with {emotion} emotion",
        "add {style} commentary voiceover",
    ],
    "premium": [
        "formal verification of {complex_system}",
        "prove the correctness of {complex_structure}",
        "design a new {advanced_concept} for {extreme_scenario}",
        "write a {complex_tool} for a {niche_domain} language",
        "implement a full {complex_system} with {advanced_feature}",
        "design a cryptographic protocol for {security_scenario}",
        "build a {ml_system} from scratch",
        "implement a {cs_framework}",
        "design a new {storage_type} engine",
        "write a theorem prover for {logic_type}",
        "implement a {hardware_level} kernel",
        "design a fault-tolerant {distributed_system}",
        "build a {analysis_tool} engine",
        "implement a {crypto_scheme} scheme",
        "design a new {ml_concept} architecture",
        "write a {virtualization_tool} from scratch",
        "implement a concurrent {memory_manager}",
        "design a global-scale {infra_system}",
        "build a real-time {financial_system}",
        "implement a {consensus_protocol} protocol",
    ],
    "meta": [
        "which model should i use for {task_type}",
        "route this query to the right llm",
        "what tier is this {task_type} query",
        "classify this request: {example_query}",
        "should i use local or cloud for {task_type}",
        "what model can handle {task_type}",
        "why was this routed to {tier_name}",
        "check routing decision for {example_query}",
        "analyze my routing pattern for {task_type}",
        "debug routing: {example_query}",
        "what llm is best for {task_type}",
        "recommend a model for {task_type}",
    ],
}

# ── Word pools for templates ─────────────────────────────────────────
POOLS = {
    "thing": ["docker", "kubernetes", "python", "linux", "git", "api", "database", "server", "function", "variable"],
    "concept": ["yagni", "solid", "rest", "microservices", "load balancing", "caching", "oauth", "websockets"],
    "simple_task": ["sort a list", "read a file", "parse json", "loop through array", "create directory"],
    "lang": ["python", "rust", "go", "javascript", "typescript", "java", "c++", "ruby", "bash"],
    "things": ["all running processes", "all files in a directory", "all environment variables", "all open ports"],
    "a": ["json", "xml", "csv", "yaml", "markdown"],
    "b": ["yaml", "json", "html", "csv", "markdown"],
    "code_snippet": ["def foo(): return x+1", "for i in range(10): print(i)", "if x > 5: return True"],
    "tool": ["python", "node", "git", "docker", "nginx"],
    "os": ["windows", "linux", "macos", "ubuntu", "debian"],
    "attribute": ["ip address", "version", "port", "status", "size"],
    "joke_type": ["programming", "tech", "dad", "science"],
    "place": ["london", "tokyo", "new york", "paris", "sydney"],
    "number": ["42", "101", "256", "7", "0"],
    "country": ["france", "japan", "brazil", "india", "australia"],
    "host": ["google.com", "localhost", "example.com", "github.com"],
    "n": ["2", "10", "100", "5", "3"],
    "m": ["3", "20", "200", "7", "4"],
    "greeting": ["hello", "hi", "hey", "good morning", "good evening"],
    "city": ["hong kong", "tokyo", "london", "berlin", "toronto"],
    "framework": ["fastapi", "express", "django", "flask", "spring", "nextjs"],
    "app_type": ["api", "service", "app", "server", "microservice", "backend", "frontend"],
    "purpose": ["manage users", "handle payments", "send emails", "process orders", "track analytics"],
    "tech": ["react", "vue", "angular", "svelte", "tailwind"],
    "feature": ["login", "pagination", "search", "sorting", "filtering", "authentication"],
    "component": ["api endpoint", "function", "class", "module", "service", "middleware"],
    "bug_desc": ["null pointer exception", "index out of range", "memory leak", "race condition"],
    "platform": ["vercel", "netlify", "heroku", "aws", "gcp", "docker"],
    "project_type": ["node project", "python project", "go project", "rust project"],
    "ci_tool": ["github actions", "gitlab ci", "jenkins", "circle ci"],
    "query_purpose": ["get active users", "find duplicates", "calculate revenue", "join tables"],
    "automation_task": ["backup logs", "clean temp files", "deploy app", "run tests"],
    "db": ["postgres", "mysql", "sqlite", "mongodb"],
    "linter": ["eslint", "prettier", "black", "rustfmt"],
    "pattern": ["factory pattern", "observer pattern", "singleton", "dependency injection"],
    "use_case": ["event handling", "state management", "data streaming"],
    "distributed_system": ["rate limiter", "cache", "lock manager", "queue", "file system"],
    "scale": ["1m", "10m", "100m", "1b", "1k"],
    "system_type": ["chat system", "analytics system", "game server", "api gateway", "streaming pipeline"],
    "algorithm": ["raft consensus", "consistent hashing", "lru cache", "bloom filter", "merge sort"],
    "strategy": ["zero-downtime", "blue-green", "canary", "rolling update"],
    "data_structure": ["lru cache", "skip list", "b-tree", "hash map", "ring buffer"],
    "advanced_feature": ["hot reload", "backpressure", "auto-scaling", "circuit breaker", "retry logic"],
    "complex_component": ["query optimizer", "sql parser", "template engine", "orm"],
    "distributed_concept": ["vector clock", "crdt", "gossip protocol", "paxos"],
    "complex_scenario": ["multi-region deployment", "disaster recovery", "cross-dc replication"],
    "variant": ["virtual nodes", "write-ahead log", "quorum reads"],
    "network_component": ["tcp load balancer", "http proxy", "dns resolver"],
    "low_level_component": ["memory allocator", "garbage collector", "context switcher"],
    "systems_lang": ["rust", "c", "c++", "zig"],
    "primitive": ["lock", "queue", "counter", "semaphore"],
    "tool_name": ["etcd", "zookeeper", "redis", "consul"],
    "infra_component": ["cdn", "dns", "load balancer", "api gateway"],
    "parser_type": ["protocol buffer parser", "json parser", "csv parser", "markdown parser"],
    # Vision pool
    "visual_input": ["image", "photo", "picture", "screenshot", "scan"],
    "chart_type": ["bar chart", "line graph", "pie chart", "scatter plot", "heatmap"],
    "object_type": ["product", "document", "logo", "label", "component"],
    "document_type": ["screenshot", "scan", "document", "form", "receipt"],
    "objects": ["people", "animals", "cars", "tables", "chairs"],
    "diagram_type": ["flowchart", "uml diagram", "architecture diagram", "network diagram"],
    "design_type": ["ui mockup", "wireframe", "prototype", "poster"],
    "subject": ["main subject", "dominant color", "focal point", "background"],
    "infographic_type": ["chart", "graph", "table", "timeline", "map"],
    "feature_v": ["faces", "text", "logos", "barcodes", "shapes"],
    # Video pool
    "content_script": ["script", "article", "blog post", "story", "tutorial"],
    "duration": ["30 second", "60 second", "2 minute", "15 second", "5 minute"],
    "product_type": ["software", "app", "gadget", "service", "course"],
    "content_type": ["article", "blog post", "report", "paper", "documentation"],
    "source": ["text", "script", "article", "bullet points", "outline"],
    "elements": ["images", "illustrations", "icons", "shapes", "text overlays"],
    "platform_v": ["youtube", "tiktok", "instagram", "twitter", "linkedin"],
    "topic": ["programming", "cooking", "fitness", "technology", "design"],
    "theme": ["nature", "city", "space", "abstract", "corporate"],
    "voice_style": ["professional", "casual", "enthusiastic", "calm", "dramatic"],
    # Voice pool
    "language": ["english", "cantonese", "mandarin", "japanese", "spanish"],
    "audio_sample": ["recording", "clip", "sample", "file", "recording"],
    "media_type": ["video", "presentation", "animation", "slideshow"],
    "accent": ["british", "american", "australian", "cantonese", "indian"],
    "style": ["celebrity", "character", "cartoon", "robot", "monster"],
    "use_case_v": ["customer service", "navigation", "smart home", "alarm", "notification"],
    "speaker_count": ["2", "3", "4", "multiple", "two"],
    "project": ["animation", "game", "podcast", "audiobook"],
    "lyrics_source": ["poem", "lyrics", "text", "song"],
    "event_type": ["public", "emergency", "sports", "airport", "store"],
    "emotion": ["happy", "sad", "angry", "excited", "calm"],
    # Premium pool
    "complex_system": ["distributed algorithm", "concurrent data structure", "cryptographic protocol"],
    "complex_structure": ["concurrent data structure", "distributed algorithm", "lock-free queue"],
    "advanced_concept": ["consensus protocol", "homomorphic encryption", "quantum algorithm"],
    "extreme_scenario": ["geo-distributed systems", "multi-region deployment", "space-grade reliability"],
    "complex_tool": ["compiler frontend", "static analyzer", "formal verifier"],
    "niche_domain": ["custom", "esoteric", "domain-specific", "functional"],
    "security_scenario": ["secure multi-party computation", "zero-knowledge proofs", "secret sharing"],
    "ml_system": ["reinforcement learning agent", "neural network framework", "recommendation engine"],
    "cs_framework": ["differentiable programming framework", "automatic differentiation system"],
    "storage_type": ["database storage engine", "key-value store", "time-series database"],
    "logic_type": ["first-order logic", "modal logic", "temporal logic", "higher-order logic"],
    "hardware_level": ["gpu kernel", "simd algorithm", "cache-coherent protocol", "interrupt handler"],
    "analysis_tool": ["symbolic execution", "static analysis", "dynamic taint analysis"],
    "crypto_scheme": ["homomorphic encryption", "attribute-based encryption", "ring signature"],
    "ml_concept": ["neural network", "attention mechanism", "generative model", "diffusion model"],
    "virtualization_tool": ["hypervisor", "container runtime", "unikernel"],
    "memory_manager": ["garbage collector", "arena allocator", "reference counter"],
    "infra_system": ["dns system", "content delivery network", "monitoring system"],
    "financial_system": ["trading engine", "payment processor", "risk analyzer"],
    "consensus_protocol": ["byzantine fault tolerance", "proof of stake", "paxos"],
    # Meta pool
    "task_type": ["coding", "writing", "analysis", "image", "video", "voice"],
    "example_query": ["write a rest api", "analyze this image", "build a compiler", "convert text to speech"],
    "tier_name": ["local", "flash", "pro", "vision", "video", "voice", "premium"],
}

def fill_template(template: str) -> str:
    """Replace {placeholders} with random values from POOLS."""
    result = template
    for key in re.findall(r"\{(\w+)\}", template):
        pool = POOLS.get(key, ["something"])
        result = result.replace("{" + key + "}", random.choice(pool), 1)
    return result

def generate_dataset(examples_per_class: int = 60) -> list:
    """Generate synthetic training data from templates."""
    data = []
    for tier in TIERS:
        templates = TEMPLATES.get(tier, [])
        if not templates:
            continue
        # Generate multiple variations per template
        target = examples_per_class
        attempts = 0
        while len([d for d in data if d[1] == tier]) < target and attempts < target * 5:
            attempts += 1
            t = random.choice(templates)
            query = fill_template(t)
            data.append((query, tier))
        count = len([d for d in data if d[1] == tier])
        print(f"  {tier}: {count} examples")
    random.shuffle(data)
    return data

# ── Embedding ────────────────────────────────────────────────────────
_EMBED_CACHE = {}
def embed(text: str) -> list:
    if text in _EMBED_CACHE:
        return _EMBED_CACHE[text]
    data = json.dumps({"model": OLLAMA_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(OLLAMA_EMBED_URL, data=data,
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=60)
    vec = json.loads(resp.read())["embedding"]
    _EMBED_CACHE[text] = vec
    return vec

# ── Features: only key engineered features + embedding ──────────────
def extract_features(text: str, embedding: list) -> list:
    feats = list(embedding)
    # Only 3 lightweight binary features
    feats.append(1 if any(w in text.lower() for w in ["image","photo","picture","screenshot","diagram","scan","ocr"]) else 0)
    feats.append(1 if any(w in text.lower() for w in ["video","animation","clip","footage","youtube","tiktok"]) else 0)
    feats.append(1 if any(w in text.lower() for w in ["voice","speech","tts","narration","audio","podcast","voiceover"]) else 0)
    return feats

# ── Balance tiers ────────────────────────────────────────────────────
def balance_tiers(X, y, tier_list):
    """Ensure all tiers have roughly equal representation."""
    from collections import Counter
    counts = Counter(y)
    target = max(counts.values())
    X_bal, y_bal = [], []
    for t in tier_list:
        tier_samples = [(X[i], y[i]) for i in range(len(y)) if y[i] == t]
        while len(tier_samples) < target:
            tier_samples.append(random.choice(tier_samples))
        random.shuffle(tier_samples)
        for x_s, y_s in tier_samples[:target]:
            X_bal.append(x_s)
            y_bal.append(y_s)
    return X_bal, y_bal

# ── Main ─────────────────────────────────────────────────────────────
def main():
    print(f"🚀 Training router classifier v2")
    print(f"   Tiers: {', '.join(TIERS)}")
    print()

    # Generate dataset
    print("  Generating synthetic training data...")
    raw_data = generate_dataset(examples_per_class=60)
    print(f"  ✓ Total: {len(raw_data)} examples")
    print()

    # Embed all
    X_raw, y_raw = [], []
    for i, (query, tier) in enumerate(raw_data):
        print(f"  Embedding ({i+1}/{len(raw_data)}): {query[:50]}...", end="\r")
        vec = embed(query)
        feats = extract_features(query, vec)
        X_raw.append(feats)
        y_raw.append(tier)
    print(f"\n  ✓ All embedded\n")

    # Balance tiers
    from collections import Counter
    print("  Before balancing:", dict(Counter(y_raw)))
    X, y = balance_tiers(X_raw, y_raw, TIERS)
    print("  After balancing:", dict(Counter(y)))
    print(f"  Total balanced: {len(X)} samples")
    print()

    # Train
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import LabelEncoder, StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import cross_val_score

    le = LabelEncoder()
    y_enc = le.fit_transform(y)

    # Pipeline: scale → logistic regression (L2, multiclass)
    clf = Pipeline([
        ("scale", StandardScaler()),
        ("lr", LogisticRegression(
            C=0.1, max_iter=1000, multi_class="multinomial",
            solver="lbfgs", random_state=42,
        )),
    ])
    clf.fit(X, y_enc)
    train_acc = clf.score(X, y_enc)
    print(f"  Training accuracy: {train_acc:.1%}")

    # Cross-validation
    scores = cross_val_score(clf, X, y_enc, cv=5)
    print(f"  5-fold CV accuracy: {scores.mean():.1%} ± {scores.std():.1%}")

    # Per-class accuracy
    from sklearn.metrics import classification_report
    y_pred = clf.predict(X)
    print("\n  Per-class report:")
    print(f"  {'Tier':>8}  {'Prec':>6} {'Recall':>6} {'F1':>6}")
    cr = classification_report(y_enc, y_pred, target_names=le.classes_, output_dict=True)
    for t in TIERS:
        if t in cr:
            print(f"  {t:>8}: {cr[t]['precision']:.3f} {cr[t]['recall']:.3f} {cr[t]['f1-score']:.3f}")
    print(f"  {'avg':>8}: {cr['weighted avg']['precision']:.3f} {cr['weighted avg']['recall']:.3f} {cr['weighted avg']['f1-score']:.3f}")

    # Save
    model = {
        "classifier": clf,
        "label_encoder": le,
        "tiers": TIERS,
        "feature_dim": len(X[0]),
        "embed_dim": len(embed("test")),
        "n_train": len(X),
        "train_accuracy": train_acc,
        "cv_score": f"{scores.mean():.1%} ± {scores.std():.1%}",
    }
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    print(f"\n  💾 Saved: {MODEL_PATH}")

    # Test predictions
    print("\n  Sample predictions:")
    tests = [
        "hello world",
        "write a fastapi crud API for user management",
        "design a distributed consensus protocol with raft",
        "what is in this photo",
        "generate a 60 second promotional video for youtube",
        "convert this article to speech with a british accent",
        "formal verification of a distributed consensus algorithm",
        "which model should I use for this coding task",
        "explain what is a microservice",
        "implement consistent hashing with virtual nodes in go",
        "analyze this chart and tell me the trend",
        "create a youtube intro animation for my channel",
    ]
    for q in tests:
        v = embed(q)
        f = extract_features(q, v)
        pred = clf.predict([f])[0]
        probs = clf.predict_proba([f])[0]
        tier = le.inverse_transform([pred])[0]
        conf = max(probs)
        # Show top 3
        top3 = sorted(zip(le.classes_, probs), key=lambda x: -x[1])[:3]
        top3_str = " | ".join(f"{t}: {p:.0%}" for t, p in top3)
        print(f"    [{tier:>7} ({conf:.0%})] {q[:55]}")
        print(f"      top3: {top3_str}")

    print("\n✅ Done!")

if __name__ == "__main__":
    main()
