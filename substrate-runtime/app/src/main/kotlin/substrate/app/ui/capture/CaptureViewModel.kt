package substrate.app.ui.capture

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import substrate.core.model.PipelineResult
import substrate.core.orchestrator.EventPipeline

class CaptureViewModel(private val pipeline: EventPipeline) : ViewModel() {

    private val _lastResult = MutableStateFlow<PipelineResult?>(null)
    val lastResult: StateFlow<PipelineResult?> = _lastResult

    private val _isSubmitting = MutableStateFlow(false)
    val isSubmitting: StateFlow<Boolean> = _isSubmitting

    fun submit(actor: String, text: String) {
        if (text.isBlank() || _isSubmitting.value) return
        _isSubmitting.value = true
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) { pipeline.submit(actor = actor, text = text) }
            _lastResult.value = result
            _isSubmitting.value = false
        }
    }
}
