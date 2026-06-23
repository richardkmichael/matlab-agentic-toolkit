function [filtered, peaks] = processSignalBank(signals, filterCoeffs)
    % signals: 2000 x 4096 matrix (2000 signals, 4096 samples each)
    % filterCoeffs: FIR filter coefficients (1x64 vector)
    [nSignals, nSamples] = size(signals);
    filtered = zeros(nSignals, nSamples);
    peaks = cell(nSignals, 1);

    % Filter each signal
    for i = 1:nSignals
        filtered(i,:) = filter(filterCoeffs, 1, signals(i,:));
    end

    % Find peaks in each filtered signal
    for i = 1:nSignals
        [pks, locs] = findpeaks(filtered(i,:), ...
            'MinPeakHeight', 0.5, ...
            'MinPeakDistance', 20);
        peaks{i} = struct('heights', pks, 'locations', locs);
    end
end
