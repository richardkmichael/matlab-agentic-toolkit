function results = interpolateFrames(breakpts, values, frames)
    % breakpts, values: a shared interpolation curve (1 x K).
    % frames: cell array of query-point vectors, each interpolated against the
    %          SAME curve. interp1 is called per query point, so it reprocesses
    %          the breakpoints on every one of the calls.
    results = cell(size(frames));
    for f = 1:numel(frames)
        q = frames{f};
        y = zeros(size(q));
        for i = 1:numel(q)
            y(i) = interp1(breakpts, values, q(i), 'linear');
        end
        results{f} = y;
    end
end
