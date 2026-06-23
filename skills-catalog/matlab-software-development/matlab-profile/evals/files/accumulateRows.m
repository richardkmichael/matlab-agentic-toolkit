function out = accumulateRows(n)
    % Builds an n-by-3 table of values by growing the result one row at a time.
    % Each iteration reallocates and copies the whole array, so the cost grows
    % quadratically with n.
    out = [];
    for i = 1:n
        row = [i, i^2, sqrt(i)];
        out = [out; row];
    end
end
