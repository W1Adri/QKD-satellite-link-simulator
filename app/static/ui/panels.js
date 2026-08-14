// ---------------------------------------------------------------------------
// app/static/ui/panels.js
// ---------------------------------------------------------------------------
// Purpose : Standalone DOM UI helpers — slider/number-input synchronisation
//           and collapsible panel accordions. No rendering dependencies.
// Exports : initSliders, createPanelAccordions
// ---------------------------------------------------------------------------

function setupSliderSync(sliderConfig) {
  sliderConfig.forEach(({ sliderId, numberId, valueId }) => {
    const slider = document.getElementById(sliderId);
    const numberInput = document.getElementById(numberId);
    const valueDisplay = valueId ? document.getElementById(valueId) : null;

    if (!slider || !numberInput) return;

    slider.addEventListener('input', () => {
      numberInput.value = slider.value;
      if (valueDisplay) valueDisplay.textContent = slider.value;
    });

    numberInput.addEventListener('input', () => {
      slider.value = numberInput.value;
      if (valueDisplay) valueDisplay.textContent = numberInput.value;
    });

    numberInput.addEventListener('change', () => {
      const min = parseFloat(slider.min);
      const max = parseFloat(slider.max);
      let value = parseFloat(numberInput.value);
      if (isNaN(value)) {
        value = min;
      }
      value = Math.max(min, Math.min(max, value));
      numberInput.value = value;
      slider.value = value;
      if (valueDisplay) valueDisplay.textContent = value;
    });

    if (valueDisplay) {
      valueDisplay.textContent = numberInput.value;
    }
  });
}

export function initSliders() {
    const sliderConfigurations = [
        { sliderId: 'semiMajorSlider', numberId: 'semiMajor' },
        { sliderId: 'optToleranceSlider', numberId: 'optToleranceA' },
        { sliderId: 'optMinRotSlider', numberId: 'optMinRot' },
        { sliderId: 'optMaxRotSlider', numberId: 'optMaxRot' },
        { sliderId: 'optMinOrbSlider', numberId: 'optMinOrb' },
        { sliderId: 'optMaxOrbSlider', numberId: 'optMaxOrb' },
        { sliderId: 'eccentricitySlider', numberId: 'eccentricity' },
        { sliderId: 'inclinationSlider', numberId: 'inclination' },
        { sliderId: 'raanSlider', numberId: 'raan' },
        { sliderId: 'argPerigeeSlider', numberId: 'argPerigee' },
        { sliderId: 'meanAnomalySlider', numberId: 'meanAnomaly' },
        { sliderId: 'satApertureSlider', numberId: 'satAperture' },
        { sliderId: 'groundApertureSlider', numberId: 'groundAperture' },
        { sliderId: 'wavelengthSlider', numberId: 'wavelength' },
        { sliderId: 'samplesPerOrbitSlider', numberId: 'samplesPerOrbit' },
        { sliderId: 'weatherSamplesSlider', numberId: 'weatherSamples' },
        { sliderId: 'photonRateSlider', numberId: 'photonRate' },
        { sliderId: 'detectorEfficiencySlider', numberId: 'detectorEfficiency' },
        { sliderId: 'darkCountRateSlider', numberId: 'darkCountRate' },
        { sliderId: 'opticalFilterBandwidthSlider', numberId: 'opticalFilterBandwidth' },
    ];
    setupSliderSync(sliderConfigurations);
}

// Turn panel headers into accordions (collapsible sections)
export function createPanelAccordions() {
  try {
    const panels = document.querySelectorAll('.panel-section');
    panels.forEach((panel) => {
      const hdr = panel.querySelector('header');
      if (!hdr) return;
      hdr.style.cursor = 'pointer';
      // add chevron
      let chev = hdr.querySelector('.accordion-chevron');
      if (!chev) {
        chev = document.createElement('span');
        chev.className = 'accordion-chevron';
        chev.textContent = '▾';
        chev.style.marginLeft = '8px';
        chev.style.opacity = '0.7';
        hdr.appendChild(chev);
      }
      // start expanded by default; collapse when clicked
      hdr.addEventListener('click', (ev) => {
        // ignore clicks on info buttons
        if (ev.target && ev.target.classList && ev.target.classList.contains('info-button')) return;
        panel.classList.toggle('collapsed');
        const collapsed = panel.classList.contains('collapsed');
        chev.textContent = collapsed ? '▸' : '▾';
        const contentChildren = Array.from(panel.children).filter((c) => c !== hdr);
        contentChildren.forEach((el) => { el.style.display = collapsed ? 'none' : ''; });
      });
    });
  } catch (e) { console.warn('Could not initialize panel accordions', e); }
}
