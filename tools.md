# Environment & Technical Tooling
**Hardware & OS**: Dual-boot development machine running Kubuntu Linux (primary) and MacBook. 
**Access**: Claude Code (local terminal agent) and any required academic literature (ArXiv, etc.).

**Core Stack & Configurations**:
- **C++ / Infrastructure**: Deeply involved in the PerceptionMetrics codebase. Must strictly respect dataset abstractions across 3D and segmentation evaluations, null-safe error handling for YOLO dataset splits, and clean application states on load.
- **Docker / DevOps**: Multi-stage build pipelines for JdeRobot RoboticsBackend optimization.
- **Python / AI Theory**: PyTorch (for mathematical adversarial testing), `sqlglot` for AST parsing, sliding-window temporal pipelines.
- **Vocal Drill Execution**: Use native Linux audio capture (e.g., `arecord -d 300 -f cd -t wav today_speech.wav`) or browser Web Audio API for the 5-minute daily monologue.

**Agent Rule**: Claude Code must write shell commands, build scripts, and C++/Python code that natively compiles and runs on Kubuntu Linux. No assumptions of Windows PowerShell or macOS-exclusive binaries.