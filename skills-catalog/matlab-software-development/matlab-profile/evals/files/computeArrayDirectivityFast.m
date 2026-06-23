function D = computeArrayDirectivityFast(elemPositions, angles, freq, elemPattern)
    % Memory-optimized rewrite of computeArrayDirectivity.
    % Same result, but it does not replicate the angle grid across elements
    % (no repmat) and evaluates the element pattern once instead of N times,
    % since the pattern is identical for every element.

    arguments
        elemPositions (3,:) double
        angles (2,:) double
        freq (1,1) double
        elemPattern function_handle
    end

    N = size(elemPositions, 2);  % number of elements
    M = size(angles, 2);         % number of angles
    c = 299792458;               % speed of light

    % Element response: same for every element, so evaluate once over the M
    % angles (no repmat, no N*M redundant evaluation).
    elemResponse = elemPattern(angles(1,:), angles(2,:));  % 1 x M
    elemResponse = elemResponse(:);                        % M x 1

    % Steering vectors (necessary linear algebra, unchanged).
    azRad = deg2rad(angles(1,:));
    elRad = deg2rad(angles(2,:));
    unitVecs = [cos(elRad).*cos(azRad); cos(elRad).*sin(azRad); sin(elRad)];  % 3 x M
    delays = elemPositions.' * unitVecs;                   % N x M
    steeringVectors = exp(-1j * 2 * pi * freq / c * delays);  % N x M

    % Array response via implicit expansion: (M x 1) .* (M x N).
    arrayResponse = elemResponse .* steeringVectors.';     % M x N

    weights = ones(N, 1) / N;
    pattern = arrayResponse * weights;                     % M x 1 complex pattern

    patternPower = abs(pattern).^2;
    avgPower = mean(patternPower);
    D = 10 * log10(patternPower / avgPower);               % M x 1 directivity in dBi
end
