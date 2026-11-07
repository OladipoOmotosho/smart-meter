// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {SafeCast} from "@openzeppelin/contracts/utils/math/SafeCast.sol";

/// @title MeterCommitmentRegistry
/// @notice Stores one fingerprint (a SHA-256 digest) per meter reading.
///         A fingerprint can be added once and never replaced.
/// @dev The registry checks write authority and preserves the first digest.
contract MeterCommitmentRegistry is AccessControl {
    /// Accounts with this role may commit fingerprints.
    bytes32 public constant AGGREGATOR_ROLE = keccak256("AGGREGATOR_ROLE");

    /// What is stored for each reading.
    struct Commitment {
        bytes32 digest; // SHA-256 of the canonical reading bytes
        uint64 committedAt; // block timestamp when it was committed
        address submitter; // account that committed it
    }

    /// Emitted once for every successful commit.
    event Committed(bytes32 indexed recordKey, bytes32 digest, address indexed submitter, uint64 committedAt);

    /// A fingerprint already exists for this record key.
    error AlreadyCommitted(bytes32 recordKey);

    /// The zero digest is excluded by this registry's API convention.
    error ZeroDigest();
    error InvalidAdmin();

    mapping(bytes32 => Commitment) private commitments;

    /// @param admin account that receives DEFAULT_ADMIN_ROLE and can grant AGGREGATOR_ROLE
    constructor(address admin) {
        if (admin == address(0)) revert InvalidAdmin();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /// @notice Save the fingerprint for one reading.
    /// Requirements:
    ///  - only AGGREGATOR_ROLE may call it
    ///  - digest must not be zero (ZeroDigest)
    ///  - recordKey must not already have a commitment (AlreadyCommitted)
    ///  - store digest, block timestamp and msg.sender, then emit Committed
    function commit(bytes32 recordKey, bytes32 digest) external onlyRole(AGGREGATOR_ROLE) {
        if (digest == bytes32(0)) revert ZeroDigest();
        if (commitments[recordKey].digest != bytes32(0)) revert AlreadyCommitted(recordKey);
        uint64 committedAt = SafeCast.toUint64(block.timestamp);
        commitments[recordKey] = Commitment(digest, committedAt, msg.sender);
        emit Committed(recordKey, digest, msg.sender, committedAt);
    }

    /// @notice Return the stored commitment. All fields are zero if none exists.
    function getCommitment(bytes32 recordKey) external view returns (Commitment memory) {
        return commitments[recordKey];
    }

    /// @notice True if a fingerprint has been committed for this record key.
    function isCommitted(bytes32 recordKey) external view returns (bool) {
        return commitments[recordKey].digest != bytes32(0);
    }
}
