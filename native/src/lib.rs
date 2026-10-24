use numpy::{PyArray1, PyArray2, PyArray3, PyReadonlyArray1, PyReadonlyArray2, IntoPyArray,
            PyArrayMethods, PyUntypedArrayMethods};
use pyo3::prelude::*;
use rustfft::{FftPlanner, num_complex::Complex};
use std::cell::RefCell;

thread_local! {
    static PLANNER: RefCell<FftPlanner<f32>> = RefCell::new(FftPlanner::new());
}

fn apply_tilt_core(magnitude_db: &[f32], freqs: &[f32], tilt_db: f32, pivot_hz: f32) -> Vec<f32> {
    if tilt_db.abs() < 0.01 {
        return magnitude_db.to_vec();
    }

    let pivot = pivot_hz.max(1.0);
    let len = magnitude_db.len().min(freqs.len());
    let mut out = Vec::with_capacity(len);

    for i in 0..len {
        let freq = freqs[i].max(20.0);
        let octaves = (freq / pivot).log2();
        out.push(magnitude_db[i] + octaves * tilt_db);
    }

    out
}

fn correlation_core(left: &[f32], right: &[f32]) -> f64 {
    let n = left.len().min(right.len());
    if n == 0 {
        return 0.0;
    }

    let inv_n = 1.0 / n as f64;
    let mean_l = left.iter().take(n).map(|&v| v as f64).sum::<f64>() * inv_n;
    let mean_r = right.iter().take(n).map(|&v| v as f64).sum::<f64>() * inv_n;

    let mut l_energy = 0.0f64;
    let mut r_energy = 0.0f64;
    let mut cross = 0.0f64;

    for i in 0..n {
        let lv = left[i] as f64 - mean_l;
        let rv = right[i] as f64 - mean_r;
        l_energy += lv * lv;
        r_energy += rv * rv;
        cross += lv * rv;
    }

    let denom = (l_energy * r_energy).sqrt();
    if denom < 1e-20 {
        0.0
    } else {
        (cross / denom).clamp(-1.0, 1.0)
    }
}


/// Apply a 256-entry RGB LUT to spectrogram history columns and write into buffer_data.
///
/// history:     (history_len, display_h)  f32 in [0, 1]
/// lut:         (256, 3)                  u8  RGB
/// buffer_data: (display_h, history_len, 3) u8  BGR output (Qt RGB888)
/// start_col, end_col: column range to update (wrapping around history_len)
#[pyfunction]
fn apply_colormap<'py>(
    _py: Python<'py>,
    history: PyReadonlyArray2<'py, f32>,
    lut: PyReadonlyArray2<'py, u8>,
    buffer_data: &Bound<'py, PyArray3<u8>>,
    start_col: usize,
    end_col: usize,
    history_len: usize,
) -> PyResult<()> {
    let hist = history.as_array();
    let lut_arr = lut.as_array();
    let mut buf = unsafe { buffer_data.as_array_mut() };
    let display_h = buf.shape()[0];

    for raw_idx in start_col..end_col {
        let col = raw_idx % history_len;
        let column = hist.row(col);

        for y in 0..display_h {
            let val = column[y];
            let idx = ((val * 255.0) as i32).clamp(0, 255) as usize;
            // Write reversed (bottom-to-top → top-to-bottom)
            let ry = display_h - 1 - y;
            buf[[ry, col, 0]] = lut_arr[[idx, 0]];
            buf[[ry, col, 1]] = lut_arr[[idx, 1]];
            buf[[ry, col, 2]] = lut_arr[[idx, 2]];
        }
    }
    Ok(())
}



/// Generate a spectrogram column from FFT magnitude data.
///
/// norm:      normalized magnitude [0, 1] per bin
/// px_int:    pixel index mapping for each bin (into display_h)
/// display_h: height of the spectrogram display
///
/// Returns: column array of shape (display_h,) f32
#[pyfunction]
fn generate_spectrogram_column<'py>(
    py: Python<'py>,
    norm: PyReadonlyArray1<'py, f32>,
    px_int: PyReadonlyArray1<'py, i32>,
    n_bins: usize,
    display_h: usize,
) -> PyResult<Bound<'py, PyArray1<f32>>> {
    let norm_arr = norm.as_array();
    let px_arr = px_int.as_array();
    let mut column = vec![0.0f32; display_h];

    let limit = n_bins.min(norm_arr.len()).min(px_arr.len());

    // Maximum scatter
    for i in 0..limit {
        let px = px_arr[i] as usize;
        if px < display_h {
            let val = norm_arr[i];
            if val > column[px] {
                column[px] = val;
            }
        }
    }

    // Linear interpolation to fill gaps between non-zero entries
    let mut first_nz: Option<usize> = None;
    let mut last_nz: Option<usize> = None;
    for i in 0..display_h {
        if column[i] > 0.0 {
            if first_nz.is_none() {
                first_nz = Some(i);
            }
            last_nz = Some(i);
        }
    }

    if let (Some(first), Some(last)) = (first_nz, last_nz) {
        if last > first {
            // Find all non-zero positions
            let mut nz_positions: Vec<usize> = Vec::new();
            let mut nz_values: Vec<f32> = Vec::new();
            for i in first..=last {
                if column[i] > 0.0 {
                    nz_positions.push(i);
                    nz_values.push(column[i]);
                }
            }

            // Interpolate between consecutive non-zero entries
            for seg in 0..nz_positions.len() - 1 {
                let p0 = nz_positions[seg];
                let p1 = nz_positions[seg + 1];
                let v0 = nz_values[seg];
                let v1 = nz_values[seg + 1];
                if p1 > p0 + 1 {
                    let span = (p1 - p0) as f32;
                    for j in (p0 + 1)..p1 {
                        let t = (j - p0) as f32 / span;
                        let interp = v0 + t * (v1 - v0);
                        if interp > column[j] {
                            column[j] = interp;
                        }
                    }
                }
            }
        }
    }

    Ok(column.into_pyarray(py).into())
}



/// Write filtered + raw audio data into circular buffers (for LoudnessMeter).
///
/// Replaces the Python per-sample loop with a bulk memcpy.
/// buffer:      (buf_len, channels) f64  — K-weighted circular buffer
/// raw_buffer:  (buf_len, channels) f64  — raw circular buffer
/// filtered:    (n_samples, channels) f64 — new K-weighted data
/// raw_data:    (n_samples, channels) f64 — new raw data
/// buf_pos:     current write position
///
/// Returns: new buf_pos after writing
#[pyfunction]
fn circular_buffer_write<'py>(
    _py: Python<'py>,
    buffer: &Bound<'py, PyArray2<f64>>,
    raw_buffer: &Bound<'py, PyArray2<f64>>,
    filtered: PyReadonlyArray2<'py, f64>,
    raw_data: PyReadonlyArray2<'py, f64>,
    buf_pos: usize,
) -> PyResult<usize> {
    let mut buf = unsafe { buffer.as_array_mut() };
    let mut raw_buf = unsafe { raw_buffer.as_array_mut() };
    let filt = filtered.as_array();
    let raw = raw_data.as_array();

    let buf_len = buf.shape()[0];
    let channels = buf.shape()[1].min(filt.shape()[1]);
    let n = filt.shape()[0];
    let mut pos = buf_pos;

    // Bulk write — if the block fits without wrapping, do a single slice copy
    let end_pos = pos + n;
    if end_pos <= buf_len {
        for c in 0..channels {
            for i in 0..n {
                buf[[pos + i, c]] = filt[[i, c]];
                raw_buf[[pos + i, c]] = raw[[i, c]];
            }
        }
        pos = end_pos;
    } else {
        // Wrapping write
        for i in 0..n {
            let wp = (pos + i) % buf_len;
            for c in 0..channels {
                buf[[wp, c]] = filt[[i, c]];
                raw_buf[[wp, c]] = raw[[i, c]];
            }
        }
        pos = (pos + n) % buf_len;
    }

    Ok(pos)
}



/// Reduce audio data into min/max/rms per chunk for waveform display.
///
/// data:       (n_samples, channels) f32
/// chunk_size: number of samples per output pixel
///
/// Returns: (max_buf, min_buf, rms_buf) each (n_chunks, channels) f32
#[pyfunction]
fn waveform_reduce<'py>(
    py: Python<'py>,
    data: PyReadonlyArray2<'py, f32>,
    chunk_size: usize,
) -> PyResult<(
    Bound<'py, PyArray2<f32>>,
    Bound<'py, PyArray2<f32>>,
    Bound<'py, PyArray2<f32>>,
)> {
    let arr = data.as_array();
    let n = arr.shape()[0];
    let channels = arr.shape()[1];
    let chunk_size = chunk_size.max(1);
    let n_chunks = (n + chunk_size - 1) / chunk_size;

    let mut max_buf = vec![0.0f32; n_chunks * channels];
    let mut min_buf = vec![0.0f32; n_chunks * channels];
    let mut rms_buf = vec![0.0f32; n_chunks * channels];

    for chunk_idx in 0..n_chunks {
        let start = chunk_idx * chunk_size;
        let end = (start + chunk_size).min(n);
        let len = end - start;
        if len == 0 {
            continue;
        }

        for c in 0..channels {
            let mut mx = f32::NEG_INFINITY;
            let mut mn = f32::INFINITY;
            let mut sum_sq = 0.0f32;

            for i in start..end {
                let v = arr[[i, c]];
                if v > mx { mx = v; }
                if v < mn { mn = v; }
                sum_sq += v * v;
            }

            let idx = chunk_idx * channels + c;
            max_buf[idx] = mx;
            min_buf[idx] = mn;
            rms_buf[idx] = (sum_sq / len as f32).sqrt();
        }
    }

    let max_arr = numpy::ndarray::Array2::from_shape_vec((n_chunks, channels), max_buf)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let min_arr = numpy::ndarray::Array2::from_shape_vec((n_chunks, channels), min_buf)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let rms_arr = numpy::ndarray::Array2::from_shape_vec((n_chunks, channels), rms_buf)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    Ok((
        max_arr.into_pyarray(py).into(),
        min_arr.into_pyarray(py).into(),
        rms_arr.into_pyarray(py).into(),
    ))
}



/// Build a 256-entry RGB LUT from a list of (position, r, g, b) stops.
///
/// stops: list of (f32, u8, u8, u8) — position [0..1] and RGB values
///
/// Returns: (256, 3) u8 array
#[pyfunction]
fn build_colormap<'py>(
    py: Python<'py>,
    stops: Vec<(f32, u8, u8, u8)>,
) -> PyResult<Bound<'py, PyArray2<u8>>> {
    let n = 256usize;
    let mut lut = vec![0u8; n * 3];

    for i in 0..n {
        let t = i as f32 / (n - 1) as f32;

        for j in 0..stops.len() - 1 {
            let (t0, r0, g0, b0) = stops[j];
            let (t1, r1, g1, b1) = stops[j + 1];
            if t >= t0 && t <= t1 {
                let frac = if t1 > t0 { (t - t0) / (t1 - t0) } else { 0.0 };
                lut[i * 3] = (r0 as f32 + (r1 as f32 - r0 as f32) * frac) as u8;
                lut[i * 3 + 1] = (g0 as f32 + (g1 as f32 - g0 as f32) * frac) as u8;
                lut[i * 3 + 2] = (b0 as f32 + (b1 as f32 - b0 as f32) * frac) as u8;
                break;
            }
        }
    }

    let arr = numpy::ndarray::Array2::from_shape_vec((n, 3), lut)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    Ok(arr.into_pyarray(py).into())
}



/// Compute stereo correlation coefficient.
/// Returns value in [-1, +1]. +1 = mono, 0 = unrelated, -1 = out of phase.
#[pyfunction]
fn correlation<'py>(
    _py: Python<'py>,
    left: PyReadonlyArray1<'py, f32>,
    right: PyReadonlyArray1<'py, f32>,
) -> PyResult<f64> {
    let l = left.as_array();
    let r = right.as_array();
    Ok(correlation_core(l.as_slice().unwrap_or(&[]), r.as_slice().unwrap_or(&[])))
}



/// Apply gain multiplier to audio blocks in-place.
/// blocks: list of (n_samples, channels) f32 arrays
/// Returns: concatenated result as single array
#[pyfunction]
fn apply_gain_and_concat<'py>(
    py: Python<'py>,
    blocks: Vec<PyReadonlyArray2<'py, f32>>,
    gain: f32,
    target_channels: usize,
) -> PyResult<Bound<'py, PyArray2<f32>>> {
    // Calculate total size
    let total_samples: usize = blocks.iter().map(|b| b.shape()[0]).sum();
    if total_samples == 0 || blocks.is_empty() {
        let empty = numpy::ndarray::Array2::<f32>::zeros((0, target_channels));
        return Ok(empty.into_pyarray(py).into());
    }

    let mut result = vec![0.0f32; total_samples * target_channels];
    let mut offset = 0;

    for block in &blocks {
        let arr = block.as_array();
        let n = arr.shape()[0];
        let ch = arr.shape()[1].min(target_channels);

        if gain == 1.0 {
            for i in 0..n {
                for c in 0..ch {
                    result[(offset + i) * target_channels + c] = arr[[i, c]];
                }
            }
        } else {
            for i in 0..n {
                for c in 0..ch {
                    result[(offset + i) * target_channels + c] = arr[[i, c]] * gain;
                }
            }
        }
        offset += n;
    }

    let arr = numpy::ndarray::Array2::from_shape_vec((total_samples, target_channels), result)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    Ok(arr.into_pyarray(py).into())
}



/// Compute the magnitude spectrum of audio data.
/// Returns (magnitude_db)
#[pyfunction]
fn compute_fft<'py>(
    py: Python<'py>,
    data: PyReadonlyArray1<'py, f32>,
    window: PyReadonlyArray1<'py, f32>,
    fft_size: usize,
) -> PyResult<Bound<'py, PyArray1<f32>>> {
    let input = data.as_array();
    let win = window.as_array();
    
    let n = input.len().min(fft_size).min(win.len());
    
    let mut buffer = vec![Complex { re: 0.0, im: 0.0 }; fft_size];
    for i in 0..n {
        buffer[i].re = input[i] * win[i];
    }
    
    PLANNER.with(|planner| {
        let fft = planner.borrow_mut().plan_fft_forward(fft_size);
        fft.process(&mut buffer);
    });
    
    let out_size = fft_size / 2 + 1;
    let mut mag_db = vec![0.0f32; out_size];
    
    let norm = fft_size as f32 / 4.0;
    
    for i in 0..out_size {
        let mag = (buffer[i].re * buffer[i].re + buffer[i].im * buffer[i].im).sqrt();
        let mut m = mag / norm;
        if m < 1e-10 { m = 1e-10; }
        mag_db[i] = 20.0 * m.log10();
    }
    
    let arr = numpy::ndarray::Array1::from_vec(mag_db);
    Ok(arr.into_pyarray(py).into())
}

/// Apply a spectral tilt in dB/octave around a pivot frequency.
#[pyfunction]
fn apply_tilt<'py>(
    py: Python<'py>,
    magnitude_db: PyReadonlyArray1<'py, f32>,
    freqs: PyReadonlyArray1<'py, f32>,
    tilt_db: f32,
    pivot_hz: f32,
) -> PyResult<Bound<'py, PyArray1<f32>>> {
    let mag = magnitude_db.as_array();
    let freq = freqs.as_array();
    let out = apply_tilt_core(
        mag.as_slice().unwrap_or(&[]),
        freq.as_slice().unwrap_or(&[]),
        tilt_db,
        pivot_hz,
    );
    Ok(numpy::ndarray::Array1::from_vec(out).into_pyarray(py).into())
}


/// Compute correlation per frequency band.
/// bands: Vec of (name, low_hz, high_hz)
/// Returns: HashMap of band_name -> correlation
#[pyfunction]
fn multiband_correlation<'py>(
    _py: Python<'py>,
    left: PyReadonlyArray1<'py, f32>,
    right: PyReadonlyArray1<'py, f32>,
    sample_rate: f64,
    bands: Vec<(String, f32, f32)>,
) -> PyResult<std::collections::HashMap<String, f32>> {
    let l_in = left.as_array();
    let r_in = right.as_array();
    let n = l_in.len().min(r_in.len());
    if n == 0 { return Ok(std::collections::HashMap::new()); }

    // Next power of two for FFT efficiency
    let fft_size = n.next_power_of_two();
    let mut l_buf = vec![Complex { re: 0.0, im: 0.0 }; fft_size];
    let mut r_buf = vec![Complex { re: 0.0, im: 0.0 }; fft_size];

    for i in 0..n {
        l_buf[i].re = l_in[i];
        r_buf[i].re = r_in[i];
    }

    PLANNER.with(|planner| {
        let fft = planner.borrow_mut().plan_fft_forward(fft_size);
        fft.process(&mut l_buf);
    });
    
    let mut r_fft = r_buf.clone();
    PLANNER.with(|planner| {
        let fft = planner.borrow_mut().plan_fft_forward(fft_size);
        fft.process(&mut r_fft);
    });
    let l_fft = l_buf;

    let mut results = std::collections::HashMap::new();

    for (name, lo, hi) in bands {
        let bin_lo = (lo as f64 * fft_size as f64 / sample_rate) as usize;
        let bin_hi = (hi as f64 * fft_size as f64 / sample_rate) as usize;
        
        let mut l_band = vec![Complex { re: 0.0, im: 0.0 }; fft_size];
        let mut r_band = vec![Complex { re: 0.0, im: 0.0 }; fft_size];
        
        let mut energy = 0.0f32;
        let limit = (fft_size / 2).min(bin_hi);
        let start = (1).max(bin_lo); // Ensure we don't include DC if not intended

        for i in start..=limit {
            l_band[i] = l_fft[i];
            r_band[i] = r_fft[i];
            // Mirrored bins for real iFFT
            l_band[fft_size - i] = l_fft[i].conj();
            r_band[fft_size - i] = r_fft[i].conj();
            
            energy += l_fft[i].norm_sqr() + r_fft[i].norm_sqr();
        }

        // Gating: -90dB threshold (normalized by fft_size)
        let threshold = 1e-9f32 * fft_size as f32; 
        if energy < threshold {
            results.insert(name, 0.0);
            continue;
        }

        PLANNER.with(|planner| {
            let ifft = planner.borrow_mut().plan_fft_inverse(fft_size);
            ifft.process(&mut l_band);
            ifft.process(&mut r_band);
        });

        let mut l_energy = 0.0f64;
        let mut r_energy = 0.0f64;
        let mut cross = 0.0f64;

        for i in 0..fft_size {
            let lv = l_band[i].re as f64;
            let rv = r_band[i].re as f64;
            l_energy += lv * lv;
            r_energy += rv * rv;
            cross += lv * rv;
        }

        let denom = (l_energy * r_energy).sqrt();
        let corr = if denom < 1e-20 { 0.0 } else { (cross / denom).clamp(-1.0, 1.0) as f32 };
        results.insert(name, corr);
    }

    Ok(results)
}



#[pyfunction]
fn prepare_oscilloscope_trace<'py>(
    py: Python<'py>,
    data: PyReadonlyArray1<'py, f32>,
    display_samples: usize,
    num_points: usize,
    gain_mode: i32,
    manual_gain: f32,
    prev_gain: f32,
) -> PyResult<(Bound<'py, PyArray1<f32>>, f32)> {
    let ch = data.as_slice()?;
    let n = ch.len();
    let num_pts = num_points.max(2);
    let disp_smp = display_samples.max(2).min(n);

    let search_limit = n.saturating_sub(disp_smp);
    let mut trig = search_limit as f32;

    if search_limit > 1 {
        for i in (0..search_limit).rev() {
            let y0 = ch[i];
            let y1 = ch[i + 1];
            if y0 <= 0.0 && y1 > 0.0 {
                let diff = y1 - y0;
                let frac = if diff.abs() > 1e-6 { -y0 / diff } else { 0.0 };
                trig = i as f32 + frac;
                break;
            }
        }
    }

    let mut downsampled = Vec::with_capacity(num_pts);
    let span = (disp_smp - 1) as f32;
    let max_idx = (n - 1) as f32;
    let num_pts_f = (num_pts - 1) as f32;

    for p in 0..num_pts {
        let t = (trig + (p as f32 / num_pts_f) * span).clamp(0.0, max_idx);
        let t0 = t.floor() as usize;
        let t1 = (t0 + 1).min(n - 1);
        let frac = t - (t0 as f32);
        let v = ch[t0] + frac * (ch[t1] - ch[t0]);
        downsampled.push(v);
    }

    let target = if gain_mode == 2 {
        manual_gain.max(0.05)
    } else {
        let mut peak: f32 = 0.0;
        for &v in &downsampled {
            let av = v.abs();
            if av > peak {
                peak = av;
            }
        }
        if peak < 0.0005 {
            1.0
        } else {
            (0.86 / peak).clamp(0.25, 32.0)
        }
    };

    let gain = if gain_mode == 2 {
        target
    } else {
        let alpha = if target < prev_gain { 0.45 } else { 0.16 };
        prev_gain + (target - prev_gain) * alpha
    };

    for v in &mut downsampled {
        *v = (*v * gain).clamp(-1.0, 1.0);
    }

    Ok((downsampled.into_pyarray(py).into(), gain))
}



const BS1770_P1: [f64; 12] = [
    0.001708984375, -0.010986328125, 0.031494140625, -0.07177734375,
    0.150146484375, 0.880859375, -0.118408203125, 0.05517578125,
    -0.027099609375, 0.01220703125, -0.00439453125, 0.0009765625,
];
const BS1770_P2: [f64; 12] = [
    0.0029296875, -0.0166015625, 0.046875, -0.1064453125,
    0.23046875, 0.685546875, 0.23046875, -0.1064453125,
    0.046875, -0.0166015625, 0.0029296875, 0.0,
];
const BS1770_P3: [f64; 12] = [
    0.0009765625, -0.00439453125, 0.01220703125, -0.027099609375,
    0.05517578125, -0.118408203125, 0.880859375, 0.150146484375,
    -0.07177734375, 0.031494140625, -0.010986328125, 0.001708984375,
];

#[pyfunction]
fn calculate_true_peak<'py>(
    py: Python<'py>,
    data: PyReadonlyArray2<'py, f64>,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let arr = data.as_array();
    let n_samples = arr.shape()[0];
    let n_channels = arr.shape()[1];

    let mut peaks_db = Vec::with_capacity(n_channels);

    if n_samples < 16 {
        for _ in 0..n_channels {
            peaks_db.push(-120.0);
        }
        return Ok(peaks_db.into_pyarray(py).into());
    }

    for ch in 0..n_channels {
        let col = arr.column(ch);
        let mut max_val: f64 = 0.0;

        for i in 0..n_samples {
            let s0 = col[i].abs();
            if s0 > max_val { max_val = s0; }

            let mut s1 = 0.0;
            let mut s2 = 0.0;
            let mut s3 = 0.0;

            for k in 0..12 {
                let idx = (i + k).saturating_sub(5);
                let sample = if idx < n_samples { col[idx] } else { 0.0 };
                s1 += BS1770_P1[k] * sample;
                s2 += BS1770_P2[k] * sample;
                s3 += BS1770_P3[k] * sample;
            }

            let s1_abs = s1.abs();
            let s2_abs = s2.abs();
            let s3_abs = s3.abs();

            if s1_abs > max_val { max_val = s1_abs; }
            if s2_abs > max_val { max_val = s2_abs; }
            if s3_abs > max_val { max_val = s3_abs; }
        }

        let db = 20.0 * (max_val.max(1e-6)).log10();
        peaks_db.push(db);
    }

    Ok(peaks_db.into_pyarray(py).into())
}



/// Apply cascaded second-order sections (biquads) in Transposed Direct Form II.
#[pyfunction]
fn sosfilt<'py>(
    py: Python<'py>,
    sos: PyReadonlyArray2<'py, f64>,
    data: PyReadonlyArray1<'py, f64>,
    zi: Option<PyReadonlyArray2<'py, f64>>,
) -> PyResult<(Bound<'py, PyArray1<f64>>, Bound<'py, PyArray2<f64>>)> {
    let sos_arr = sos.as_array();
    let n_sections = sos_arr.shape()[0];
    let data_arr = data.as_array();
    let n_samples = data_arr.len();

    let mut y = data_arr.to_vec();
    let mut zi_mat = match zi {
        Some(ref z) => z.as_array().to_owned(),
        None => numpy::ndarray::Array2::<f64>::zeros((n_sections, 2)),
    };

    for s in 0..n_sections {
        let a0 = sos_arr[[s, 3]];
        let inv_a0 = if a0.abs() > 1e-15 { 1.0 / a0 } else { 1.0 };
        let b0 = sos_arr[[s, 0]] * inv_a0;
        let b1 = sos_arr[[s, 1]] * inv_a0;
        let b2 = sos_arr[[s, 2]] * inv_a0;
        let a1 = sos_arr[[s, 4]] * inv_a0;
        let a2 = sos_arr[[s, 5]] * inv_a0;

        let mut z1 = zi_mat[[s, 0]];
        let mut z2 = zi_mat[[s, 1]];

        for i in 0..n_samples {
            let xi = y[i];
            let yi = b0 * xi + z1;
            z1 = b1 * xi - a1 * yi + z2;
            z2 = b2 * xi - a2 * yi;
            y[i] = yi;
        }

        zi_mat[[s, 0]] = z1;
        zi_mat[[s, 1]] = z2;
    }

    Ok((
        y.into_pyarray(py).into(),
        zi_mat.into_pyarray(py).into(),
    ))
}


/// Render stereometer point cloud directly into an RGBA (h, w, 4) uint8 buffer.
/// Fast SIMD persistence decay and dot plotting.
#[pyfunction]
fn render_stereometer_rgba<'py>(
    _py: Python<'py>,
    buffer: &Bound<'py, PyArray3<u8>>,
    left: PyReadonlyArray1<'py, f32>,
    right: PyReadonlyArray1<'py, f32>,
    cx: f32,
    cy: f32,
    radius: f32,
    zoom: f32,
    persistence: f32,
    display_mode: usize,
    guide_mode: usize,
    max_dots: usize,
    r: u8,
    g: u8,
    b: u8,
    alpha: u8,
) -> PyResult<()> {
    let mut buf = unsafe { buffer.as_array_mut() };
    let h = buf.shape()[0];
    let w = buf.shape()[1];
    if h == 0 || w == 0 {
        return Ok(());
    }

    // 1. Persistence decay across the buffer
    if persistence > 0.01 {
        let mult = ((persistence.min(0.99)) * 256.0) as u16;
        for y in 0..h {
            for x in 0..w {
                let a = buf[[y, x, 3]];
                if a > 0 {
                    buf[[y, x, 0]] = ((buf[[y, x, 0]] as u16 * mult) >> 8) as u8;
                    buf[[y, x, 1]] = ((buf[[y, x, 1]] as u16 * mult) >> 8) as u8;
                    buf[[y, x, 2]] = ((buf[[y, x, 2]] as u16 * mult) >> 8) as u8;
                    buf[[y, x, 3]] = ((a as u16 * mult) >> 8) as u8;
                }
            }
        }
    } else {
        buf.fill(0);
    }

    // 2. Subsample audio and compute coordinates
    let l_in = left.as_array();
    let r_in = right.as_array();
    let n = l_in.len().min(r_in.len());
    if n == 0 {
        return Ok(());
    }

    let step = (n / max_dots.max(1)).max(1);
    let bloom = max_dots <= 1024;
    let bloom_alpha = (alpha as u16 * 90 / 255) as u8;

    for i in (0..n).step_by(step) {
        let mut dx;
        let mut dy;

        if display_mode == 3 {
            // XY Oscilloscope
            dx = l_in[i] * zoom;
            dy = r_in[i] * zoom;
            if guide_mode == 1 {
                let mag = (dx * dx + dy * dy).sqrt();
                if mag > 0.96 {
                    let soft_mag = 0.96 + 0.035 * ((mag - 0.96) / 0.15).tanh();
                    let scale = soft_mag / mag.max(1e-7);
                    dx *= scale; dy *= scale;
                }
            } else if guide_mode == 2 {
                let mag = dx.abs().max(dy.abs());
                if mag > 0.96 {
                    let soft_mag = 0.96 + 0.035 * ((mag - 0.96) / 0.15).tanh();
                    let scale = soft_mag / mag.max(1e-7);
                    dx *= scale; dy *= scale;
                }
            }
        } else {
            // M/S Vectorscope modes
            dx = (r_in[i] - l_in[i]) * 0.5 * zoom;
            dy = (l_in[i] + r_in[i]) * 0.5 * zoom;

            if display_mode == 1 {
                // Scaled (smooth logarithmic companding without origin hole)
                let mag = (dx * dx + dy * dy).sqrt();
                let mag_safe = mag.max(1e-7);
                let scale = (1.0 + 9.0 * mag_safe).log10() / mag_safe;
                dx *= scale;
                dy *= scale;
            }

            if guide_mode == 1 {
                let mag = (dx * dx + dy * dy).sqrt();
                if mag > 0.96 {
                    let soft_mag = 0.96 + 0.035 * ((mag - 0.96) / 0.15).tanh();
                    let scale = soft_mag / mag.max(1e-7);
                    dx *= scale; dy *= scale;
                }
            } else if guide_mode == 2 {
                let mag = dx.abs().max(dy.abs());
                if mag > 0.96 {
                    let soft_mag = 0.96 + 0.035 * ((mag - 0.96) / 0.15).tanh();
                    let scale = soft_mag / mag.max(1e-7);
                    dx *= scale; dy *= scale;
                }
            } else {
                let mag = dx.abs() + dy.abs();
                if mag > 0.96 {
                    let soft_mag = 0.96 + 0.035 * ((mag - 0.96) / 0.15).tanh();
                    let scale = soft_mag / mag.max(1e-7);
                    dx *= scale; dy *= scale;
                }
            }
        }

        let px = (cx + dx * radius).round() as i32;
        let py = (cy - dy * radius).round() as i32;

        if px >= 0 && px < w as i32 && py >= 0 && py < h as i32 {
            let ux = px as usize;
            let uy = py as usize;
            buf[[uy, ux, 0]] = r;
            buf[[uy, ux, 1]] = g;
            buf[[uy, ux, 2]] = b;
            buf[[uy, ux, 3]] = alpha.max(buf[[uy, ux, 3]]);

            if bloom {
                if px > 0 {
                    let lx = ux - 1;
                    buf[[uy, lx, 0]] = r; buf[[uy, lx, 1]] = g; buf[[uy, lx, 2]] = b;
                    buf[[uy, lx, 3]] = bloom_alpha.max(buf[[uy, lx, 3]]);
                }
                if px + 1 < w as i32 {
                    let rx = ux + 1;
                    buf[[uy, rx, 0]] = r; buf[[uy, rx, 1]] = g; buf[[uy, rx, 2]] = b;
                    buf[[uy, rx, 3]] = bloom_alpha.max(buf[[uy, rx, 3]]);
                }
                if py > 0 {
                    let ty = uy - 1;
                    buf[[ty, ux, 0]] = r; buf[[ty, ux, 1]] = g; buf[[ty, ux, 2]] = b;
                    buf[[ty, ux, 3]] = bloom_alpha.max(buf[[ty, ux, 3]]);
                }
                if py + 1 < h as i32 {
                    let by = uy + 1;
                    buf[[by, ux, 0]] = r; buf[[by, ux, 1]] = g; buf[[by, ux, 2]] = b;
                    buf[[by, ux, 3]] = bloom_alpha.max(buf[[by, ux, 3]]);
                }
            }
        }
    }

    Ok(())
}


/// Render oscilloscope trace directly into an RGBA (h, w, 4) uint8 buffer.
#[pyfunction]
fn render_oscilloscope_rgba<'py>(
    _py: Python<'py>,
    buffer: &Bound<'py, PyArray3<u8>>,
    samples: PyReadonlyArray1<'py, f32>,
    center: f32,
    factor: f32,
    vertical: bool,
    clear: bool,
    r: u8,
    g: u8,
    b: u8,
    alpha: u8,
) -> PyResult<()> {
    let mut buf = unsafe { buffer.as_array_mut() };
    let h = buf.shape()[0];
    let w = buf.shape()[1];
    if h == 0 || w == 0 {
        return Ok(());
    }

    if clear {
        buf.fill(0);
    }

    let smp = samples.as_array();
    let n = smp.len();
    if n < 2 {
        return Ok(());
    }

    let long_axis = if vertical { h as f32 } else { w as f32 };
    let step_t = long_axis / (n - 1) as f32;

    for i in 0..(n - 1) {
        let t0 = i as f32 * step_t;
        let t1 = (i + 1) as f32 * step_t;
        let v0 = center - smp[i] * factor;
        let v1 = center - smp[i + 1] * factor;

        let (x0, y0, x1, y1) = if vertical {
            (v0, t0, v1, t1)
        } else {
            (t0, v0, t1, v1)
        };

        let dx = x1 - x0;
        let dy = y1 - y0;
        let steps = (dx.abs().max(dy.abs()).ceil() as usize).max(1);
        let x_inc = dx / steps as f32;
        let y_inc = dy / steps as f32;

        let mut cur_x = x0;
        let mut cur_y = y0;

        for _ in 0..=steps {
            let px = cur_x.round() as i32;
            let py = cur_y.round() as i32;

            if px >= 0 && px < w as i32 && py >= 0 && py < h as i32 {
                let ux = px as usize;
                let uy = py as usize;
                buf[[uy, ux, 0]] = r;
                buf[[uy, ux, 1]] = g;
                buf[[uy, ux, 2]] = b;
                buf[[uy, ux, 3]] = alpha.max(buf[[uy, ux, 3]]);
            }

            cur_x += x_inc;
            cur_y += y_inc;
        }
    }

    Ok(())
}


#[pymodule]
fn dsp_accel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(apply_colormap, m)?)?;
    m.add_function(wrap_pyfunction!(generate_spectrogram_column, m)?)?;
    m.add_function(wrap_pyfunction!(circular_buffer_write, m)?)?;
    m.add_function(wrap_pyfunction!(waveform_reduce, m)?)?;
    m.add_function(wrap_pyfunction!(build_colormap, m)?)?;
    m.add_function(wrap_pyfunction!(correlation, m)?)?;
    m.add_function(wrap_pyfunction!(apply_gain_and_concat, m)?)?;
    m.add_function(wrap_pyfunction!(compute_fft, m)?)?;
    m.add_function(wrap_pyfunction!(apply_tilt, m)?)?;
    m.add_function(wrap_pyfunction!(multiband_correlation, m)?)?;
    m.add_function(wrap_pyfunction!(prepare_oscilloscope_trace, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_true_peak, m)?)?;
    m.add_function(wrap_pyfunction!(sosfilt, m)?)?;
    m.add_function(wrap_pyfunction!(render_stereometer_rgba, m)?)?;
    m.add_function(wrap_pyfunction!(render_oscilloscope_rgba, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approx_eq(a: f32, b: f32, eps: f32) {
        assert!((a - b).abs() <= eps, "{a} != {b}");
    }

    #[test]
    fn tilt_is_db_per_octave() {
        let mag = [0.0, 0.0, 0.0];
        let freqs = [500.0, 1000.0, 2000.0];
        let out = apply_tilt_core(&mag, &freqs, 6.0, 1000.0);

        approx_eq(out[0], -6.0, 0.001);
        approx_eq(out[1], 0.0, 0.001);
        approx_eq(out[2], 6.0, 0.001);
    }

    #[test]
    fn correlation_ignores_dc_offset() {
        let left = [11.0, 12.0, 13.0, 14.0];
        let right = [-7.0, -6.0, -5.0, -4.0];

        assert!((correlation_core(&left, &right) - 1.0).abs() < 1e-9);
    }

    #[test]
    fn correlation_detects_inversion_with_offset() {
        let left = [11.0, 12.0, 13.0, 14.0];
        let right = [-4.0, -5.0, -6.0, -7.0];

        assert!((correlation_core(&left, &right) + 1.0).abs() < 1e-9);
    }
}
