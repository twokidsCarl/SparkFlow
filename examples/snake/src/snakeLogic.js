export const GRID_SIZE = 16;
export const INITIAL_DIRECTION = "right";
export const SCORE_PER_FOOD = 10;

const DIRECTION_VECTORS = {
  up: { x: 0, y: -1 },
  down: { x: 0, y: 1 },
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
};

export function createInitialState(random = Math.random) {
  const snake = [
    { x: 2, y: 8 },
    { x: 1, y: 8 },
    { x: 0, y: 8 },
  ];

  return {
    snake,
    direction: INITIAL_DIRECTION,
    queuedDirection: INITIAL_DIRECTION,
    food: getRandomEmptyCell(snake, random),
    score: 0,
    status: "running",
  };
}

export function queueDirection(state, nextDirection) {
  if (!DIRECTION_VECTORS[nextDirection]) {
    return state;
  }

  if (isOppositeDirection(state.direction, nextDirection)) {
    return state;
  }

  if (isOppositeDirection(state.queuedDirection, nextDirection)) {
    return state;
  }

  return {
    ...state,
    queuedDirection: nextDirection,
  };
}

export function stepGame(state, random = Math.random) {
  if (state.status !== "running") {
    return state;
  }

  const direction = state.queuedDirection;
  const vector = DIRECTION_VECTORS[direction];
  const nextHead = {
    x: state.snake[0].x + vector.x,
    y: state.snake[0].y + vector.y,
  };

  if (isOutsideBoard(nextHead)) {
    return {
      ...state,
      direction,
      status: "game-over",
    };
  }

  const ateFood = isSameCell(nextHead, state.food);
  const bodyToCheck = ateFood ? state.snake : state.snake.slice(0, -1);

  if (bodyToCheck.some((segment) => isSameCell(segment, nextHead))) {
    return {
      ...state,
      direction,
      status: "game-over",
    };
  }

  const movedSnake = [nextHead, ...state.snake];

  if (!ateFood) {
    movedSnake.pop();
  }

  return {
    snake: movedSnake,
    direction,
    queuedDirection: direction,
    food: ateFood ? getRandomEmptyCell(movedSnake, random) : state.food,
    score: ateFood ? state.score + SCORE_PER_FOOD : state.score,
    status: "running",
  };
}

export function getRandomEmptyCell(snake, random = Math.random) {
  const emptyCells = [];

  for (let y = 0; y < GRID_SIZE; y += 1) {
    for (let x = 0; x < GRID_SIZE; x += 1) {
      const occupied = snake.some((segment) => segment.x === x && segment.y === y);

      if (!occupied) {
        emptyCells.push({ x, y });
      }
    }
  }

  if (emptyCells.length === 0) {
    return null;
  }

  const index = Math.floor(random() * emptyCells.length);
  return emptyCells[index];
}

export function isOutsideBoard(cell) {
  return cell.x < 0 || cell.y < 0 || cell.x >= GRID_SIZE || cell.y >= GRID_SIZE;
}

export function isSameCell(a, b) {
  return Boolean(a && b) && a.x === b.x && a.y === b.y;
}

function isOppositeDirection(current, next) {
  return (
    (current === "up" && next === "down") ||
    (current === "down" && next === "up") ||
    (current === "left" && next === "right") ||
    (current === "right" && next === "left")
  );
}
