package substrate.app.ui.capture

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Divider
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import substrate.app.ui.SimpleViewModelFactory
import substrate.core.orchestrator.EventPipeline

/**
 * The only "screen" in the interaction model's sense of the word: the user
 * types what happened, and the substrate decides what activates. There is no
 * per-feature UI beyond this — the neural landscape and audit trail are
 * observation surfaces, not separate app sections with their own inputs.
 */
@Composable
fun CaptureScreen(pipeline: EventPipeline, modifier: Modifier = Modifier) {
    val viewModel: CaptureViewModel = viewModel(factory = SimpleViewModelFactory { CaptureViewModel(pipeline) })
    var actor by remember { mutableStateOf("dave") }
    var text by remember { mutableStateOf("") }
    val isSubmitting by viewModel.isSubmitting.collectAsState()
    val lastResult by viewModel.lastResult.collectAsState()

    Column(modifier = modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Introduce an event into the substrate")
        OutlinedTextField(value = actor, onValueChange = { actor = it }, label = { Text("actor") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = text, onValueChange = { text = it }, label = { Text("what happened") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { viewModel.submit(actor, text); text = "" }, enabled = !isSubmitting && text.isNotBlank()) {
            Text(if (isSubmitting) "Processing..." else "Submit")
        }
        if (isSubmitting) CircularProgressIndicator()

        lastResult?.let { result ->
            Divider()
            Text("Classification: ${result.classification.primaryType} (confidence ${"%.2f".format(result.classification.confidence)})")
            Text("Governance: ${if (result.governanceDecision.allowed) "ALLOWED" else "BLOCKED"}")
            Text("Execution: ${result.executionOutcome.kind}")
            Text("Commercial score: ${"%.2f".format(result.commercialAssessment.score)}")
            Text("Audit trail:")
            LazyColumn {
                items(result.auditTrail) { entry ->
                    Text("[${entry.stage}] ${entry.summary}")
                }
            }
        }
    }
}
