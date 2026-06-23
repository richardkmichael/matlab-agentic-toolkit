function D = computeArrayDirectivity(elemPositions, angles, freq, elemPattern)
    % Compute directivity pattern for a uniform array
    % elemPositions: 3 x N matrix of element positions (meters)
    % angles: 2 x M matrix [azimuth; elevation] in degrees
    % freq: operating frequency (Hz)
    % elemPattern: function handle @(az,el) -> 1xM response (same for all elements)
    %
    % For a URA 8x8: N=64 elements, M=64800 angles (360x180 grid)
    % Current memory: ~800 MB for N=64, M=64800

    arguments
        elemPositions (3,:) double
        angles (2,:) double
        freq (1,1) double
        elemPattern function_handle
    end

    N = size(elemPositions, 2);  % number of elements
    M = size(angles, 2);        % number of angles
    c = 299792458;              % speed of light

    %% Step 1: Expand angles for all elements
    % Replicate each angle N times (one per element)
    anglesExpanded = repmat(angles, 1, N);  % 2 x (N*M) — huge!

    %% Step 2: Compute element response for all element-angle pairs
    azAll = anglesExpanded(1, :);  % 1 x (N*M)
    elAll = anglesExpanded(2, :);  % 1 x (N*M)
    elemResponse = elemPattern(azAll, elAll);  % 1 x (N*M) — same pattern repeated N times!
    elemResponse = reshape(elemResponse, M, N);  % M x N

    %% Step 3: Compute steering vectors
    azRad = deg2rad(angles(1,:));  % 1 x M
    elRad = deg2rad(angles(2,:));  % 1 x M
    unitVecs = [cos(elRad).*cos(azRad); cos(elRad).*sin(azRad); sin(elRad)];  % 3 x M

    % Phase delays: N x M
    delays = elemPositions.' * unitVecs;  % N x M
    steeringVectors = exp(-1j * 2 * pi * freq / c * delays);  % N x M

    %% Step 4: Compute array response (element * steering)
    arrayResponse = elemResponse .* steeringVectors.';  % M x N element-wise

    % Sum across elements with uniform weights
    weights = ones(N, 1) / N;
    pattern = arrayResponse * weights;  % M x 1 complex pattern

    %% Step 5: Compute directivity
    patternPower = abs(pattern).^2;
    avgPower = mean(patternPower);
    D = 10 * log10(patternPower / avgPower);  % M x 1 directivity in dBi
end

% Copyright 2026 The MathWorks, Inc.
