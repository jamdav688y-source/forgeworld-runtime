package substrate.core.model

/** The seven relationship kinds the graph engine can materialize between nodes. */
enum class EdgeType {
    SEMANTIC,
    TEMPORAL,
    PROJECT,
    EVIDENCE,
    USER,
    RUNTIME,
    DEPENDENCY,
}
